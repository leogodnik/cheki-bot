"""Телеграм: приём сообщений, белый список, ответы.

Мозг и руки разделены. Этот файл ничего не понимает про чеки — он их
принимает, проверяет и записывает. Понимает agent.py.
"""

import json
import time

import requests

import config
import state as memory

from datetime import date, datetime
from pathlib import Path

import agent
import checks
import sheet

API = "https://api.telegram.org/bot{token}/{method}"
POLL_SECONDS = 30

INBOX = config.BASE_DIR / "чеки" / "входящие"
DONE = config.BASE_DIR / "чеки" / "готово"
DOUBTFUL = config.BASE_DIR / "чеки" / "спорные"


def call(token, method, **params):
    """Один вызов Bot API. Ждём чуть дольше, чем длится долгий опрос."""
    response = requests.post(
        API.format(token=token, method=method), json=params,
        timeout=POLL_SECONDS + 35,
    )
    response.raise_for_status()
    answer = response.json()
    if not answer.get("ok"):
        raise RuntimeError(answer.get("description", "телеграм ответил не ok"))
    return answer["result"]


def get_updates(token, offset):
    return call(token, "getUpdates", offset=offset, timeout=POLL_SECONDS,
                allowed_updates=["message"])


def say(token, chat_id, text):
    """Ответ в чат. Не дошёл — это не повод ронять бота."""
    try:
        call(token, "sendMessage", chat_id=chat_id, text=text)
    except (requests.RequestException, RuntimeError) as error:
        print(f"не смог ответить в чат {chat_id}: {error}")


def who(message):
    """Как называть человека в таблице. Ник есть не у всех, имя есть всегда."""
    sender = message.get("from", {})
    if sender.get("username"):
        return "@" + sender["username"]
    return sender.get("first_name") or "неизвестно"


def extract(message):
    """Любой вход сводится к паре «что разбирать» и «откуда пришло».

    Веток две: фотография и текст. Голосовые в проекте не разбираются —
    расшифровки в Bot API нет, и решение это окончательное."""
    if message.get("photo"):
        # Подпись под фотографией в первой версии не читается: чек говорит
        # сам за себя, а спорить с ним подписью — отдельная история.
        largest = max(message["photo"],
                      key=lambda size: size.get("file_size")
                      or size.get("width", 0) * size.get("height", 0))
        return {"kind": "фото", "photo": largest}
    text = (message.get("text") or "").strip()
    if text:
        return {"kind": "текст", "text": text}
    return None


def safe(name):
    """Ник в имя файла: буквы и цифры оставляем, остальное — подчёркивание."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    return cleaned or "кто-то"


def download_photo(token, photo, sender):
    """Качаем самый крупный размер в чеки/входящие/ и возвращаем путь."""
    info = call(token, "getFile", file_id=photo["file_id"])
    url = f"https://api.telegram.org/file/bot{token}/{info['file_path']}"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    INBOX.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = INBOX / f"{stamp}_{safe(sender)}.jpg"
    path.write_bytes(response.content)
    return path


def move(path, folder):
    """Файл едет в готово/ только при статусе «готово», иначе в спорные/."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    path.replace(target)
    return target


def reply_text(answer, verdict, written):
    """Одна фраза от агента плюс то, что заметили проверки."""
    if not written:
        head = "Разобрал, но в таблицу не попало — попробую позже"
    elif verdict["status"] == "готово":
        head = "Записал"
    else:
        head = "Записал с пометкой «проверить»"
    lines = [f"{head}: {answer['reply']}"]
    lines += ["— " + reason for reason in verdict["reasons"]]
    lines += ["— " + warning for warning in verdict["warnings"]]
    return "\n".join(lines)


def knock(env, st, message):
    """Чужому отвечаем один раз и молчим дальше.

    В терминал печатается готовая строка для settings.json: в срезе 3 то же
    самое будет делать панель кнопкой «Впустить»."""
    sender = message.get("from", {})
    sender_id = sender.get("id")
    if sender_id in st["refused"]:
        return
    st["refused"].append(sender_id)
    line = {"id": sender_id, "username": sender.get("username", ""),
            "name": sender.get("first_name", "")}
    print(f"постучался чужой: {who(message)}")
    print("  впустить — добавьте эту строку в settings.json, в список allowed:")
    print("  " + json.dumps(line, ensure_ascii=False))
    say(env["bot_token"], message["chat"]["id"],
        "Этот бот записывает расходы своего хозяина. "
        "Если он вас ждёт — передайте ему, что вы написали.")


def handle(env, st, message, channel, author):
    """Путь сообщения от телеграма до строки в таблице."""
    settings = config.load_settings()
    chat_id = message["chat"]["id"]
    if message.get("from", {}).get("id") not in config.allowed_ids(settings):
        knock(env, st, message)
        return

    incoming = extract(message)
    if incoming is None:
        say(env["bot_token"], chat_id,
            "Пришлите фотографию чека или напишите тратой: что, сколько и чем "
            "платили. Например: обед 850 картой")
        return

    # Отложенные строки уезжают при первой возможности — раньше, чем новая.
    delivered = sheet.flush(st, env["sheet_url"], env["sheet_secret"])
    if delivered:
        say(env["bot_token"], chat_id,
            f"Отложенные строки доехали до таблицы: {delivered}.")

    categories, source = sheet.categories(st, env["sheet_url"], env["sheet_secret"])
    if not categories:
        say(env["bot_token"], chat_id,
            "Не вижу справочник статей в таблице — разбирать не буду. Иначе "
            "в отчёте заведутся выдуманные статьи. Проверьте лист «Статьи».")
        return
    if source == "запас":
        say(env["bot_token"], chat_id,
            "Таблица не отдала справочник, работаю по последнему известному "
            "списку статей.")

    path = None
    unique_id = None
    if incoming["kind"] == "фото":
        unique_id = incoming["photo"]["file_unique_id"]
        if memory.seen(st, unique_id):
            say(env["bot_token"], chat_id, "Этот чек уже записан.")
            return
        try:
            path = download_photo(env["bot_token"], incoming["photo"], author)
        except (requests.RequestException, RuntimeError) as error:
            print(f"не скачал фотографию: {error}")
            say(env["bot_token"], chat_id,
                "Не смог скачать фотографию, пришлите ещё раз.")
            return
        # Ответа ждать 15–50 секунд, человеку надо сказать, что мы живы.
        say(env["bot_token"], chat_id, "Смотрю чек…")
        payload = str(path)
    else:
        payload = incoming["text"]

    today = date.today()
    try:
        answer = agent.parse(incoming["kind"], payload, categories, today,
                             settings["engine"])
    except agent.AgentError as error:
        # Файл остаётся во входящих: разберём, когда починится.
        print(f"агент не справился: {error}")
        say(env["bot_token"], chat_id,
            "Не смог разобрать. Попробуйте ещё раз или напишите текстом.")
        return

    if answer["intent"] == "правка":
        # Правка последней записи появится в срезе 3. Пока честно говорим,
        # что не умеем, и ничего не пишем: молча проглотить исправление
        # хуже, чем отказать.
        if path:
            move(path, DOUBTFUL)
        say(env["bot_token"], chat_id,
            "Правки пока не умею. Пришлите трату заново, целиком.")
        return

    if answer["intent"] == "не расход":
        # В таблицу не пишем вообще. Файл не помечаем разобранным: если это
        # было меню, человек может прислать настоящий чек тем же файлом.
        if path:
            move(path, DOUBTFUL)
        say(env["bot_token"], chat_id, answer["reply"])
        return

    verdict = checks.review(answer, categories, today)
    if path:
        path = move(path, DONE if verdict["status"] == "готово" else DOUBTFUL)

    row = {
        "date": answer["date"],
        "amount": answer["amount"] if checks.is_number(answer["amount"]) else "",
        "currency": answer["currency"],
        "merchant": answer["merchant"],
        "category": verdict["category"],
        "payment": answer["payment"],
        "source": "фото чека" if incoming["kind"] == "фото" else "текст",
        "who": author,
        "status": verdict["status"],
        "file": path.name if path else "",
    }
    written = sheet.deliver(st, env["sheet_url"], env["sheet_secret"], row)
    if unique_id:
        memory.remember(st, unique_id)
    say(env["bot_token"], chat_id, reply_text(answer, verdict, written))


def main():
    env = config.load_env()
    config.refuse_if_api_key()
    st = memory.load()
    print("Бот запущен, жду сообщений. Ctrl+C — выход.")
    while True:
        try:
            updates = get_updates(env["bot_token"], st["offset"])
        except (requests.RequestException, RuntimeError) as error:
            # Телеграм не отвечает — ждём и повторяем, offset не двигаем.
            print(f"телеграм не отвечает ({error}), жду пять секунд")
            time.sleep(5)
            continue
        for update in updates:
            st["offset"] = update["update_id"] + 1
            message = update.get("message")
            if message:
                try:
                    handle(env, st, message, "телеграм", who(message))
                except Exception as error:
                    # Одно сломанное сообщение не должно останавливать бота:
                    # offset уже сдвинут, следующее разберётся.
                    print(f"сообщение не обработалось: {error}")
            memory.save(st)


if __name__ == "__main__":
    main()
