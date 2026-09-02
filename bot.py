"""Телеграм: приём сообщений, белый список, ответы.

Мозг и руки разделены. Этот файл ничего не понимает про чеки — он их
принимает и кладёт в очередь на разбор, а ответ агента подаёт словами в чат.
Разбор — общий для обоих каналов, он живёт в intake.py.
"""

import json
import queue
import threading
import time

import requests

import config
import feed
import intake
import state as memory
import web

API = "https://api.telegram.org/bot{token}/{method}"
POLL_SECONDS = 30


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
    except (requests.RequestException, RuntimeError, ValueError) as error:
        print(f"не смог ответить в чат {chat_id}: {error}")


def who(message):
    """Как называть человека в таблице. Ник есть не у всех, имя есть всегда."""
    sender = message.get("from", {})
    if sender.get("username"):
        return "@" + sender["username"]
    return sender.get("first_name") or "неизвестно"


def extract(message):
    """Любой вход сводится к паре «что разбирать» и «откуда пришло».

    Веток три: фотография, текст и голосовое. Голосовые в проекте не
    разбираются — Claude не принимает звук, а Bot API расшифровки не даёт."""
    if message.get("photo"):
        # Подпись под фотографией в первой версии не читается: чек говорит
        # сам за себя, а спорить с ним подписью — отдельная история.
        largest = max(message["photo"],
                      key=lambda size: size.get("file_size")
                      or size.get("width", 0) * size.get("height", 0))
        return {"kind": "фото", "photo": largest}
    if message.get("voice") or message.get("audio"):
        return {"kind": "голос"}
    text = (message.get("text") or "").strip()
    if text:
        return {"kind": "текст", "text": text}
    return None


def download_photo(token, photo, sender):
    """Качаем самый крупный размер в чеки/входящие/ и возвращаем путь."""
    info = call(token, "getFile", file_id=photo["file_id"])
    url = f"https://api.telegram.org/file/bot{token}/{info['file_path']}"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return intake.save_photo(response.content, sender)


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


def admit(env, st, jobs, message):
    """От телеграмного сообщения до задания на разбор.

    Здесь только приём: белый список, скачивание, дубликат. Разбор — общий,
    он в intake.accept(), и зовёт его поток разбора."""
    settings = config.load_settings()
    chat_id = message["chat"]["id"]
    author = who(message)
    if message.get("from", {}).get("id") not in config.allowed_ids(settings):
        knock(env, st, message)
        return

    incoming = extract(message)
    if incoming is None:
        say(env["bot_token"], chat_id,
            "Пришлите фотографию чека или напишите тратой: что, сколько и чем "
            "платили. Например: обед 850 картой")
        return

    if incoming["kind"] == "голос":
        tell(env, chat_id, {"kind": "слово", "text": "Голосовые не умею.",
                            "note": "напишите текстом или пришлите фото чека",
                            "author": author, "channel": "телеграм"})
        return

    job = {"kind": incoming["kind"], "payload": "", "channel": "телеграм",
           "author": author, "chat_id": chat_id, "file": "", "mark": "", "task": ""}

    if incoming["kind"] == "фото":
        mark = incoming["photo"]["file_unique_id"]
        old = intake.duplicate(st, mark)
        if old:
            tell(env, chat_id, {"kind": "слово", "text": "Этот чек уже записан.",
                                "row": old.get("row"), "note": intake.when(old),
                                "author": author, "channel": "телеграм"})
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
        job.update(payload=str(path), file=path.name, mark=mark)
    else:
        job.update(payload=incoming["text"])

    jobs.put(job)


def tell(env, chat_id, event):
    """Событие в ленту и то же самое словами в чат."""
    feed.add(event)
    say(env["bot_token"], chat_id, as_text(event))


def as_text(event):
    """Событие ленты словами, для телеграма.

    Страница из тех же полей собирает свою строку — с разрядами в сумме и
    колонкой цифр. В чате разрядов не будет, зато будет фраза агента."""
    if event["kind"] != "запись":
        line = event.get("text", "")
        if event.get("row"):
            line += f" — строка {event['row']}"
        note = event.get("note")
        return f"{line}\n{note}" if note else line

    if not event["row"]:
        head = "Разобрал, но в таблицу не попало — попробую позже"
    elif event["status"] == "готово":
        head = "Записал"
    else:
        head = "Записал с пометкой «проверить»"
    lines = [f"{head}: {event['reply']}"]
    if event["row"]:
        lines[0] += f" — строка {event['row']}"
    lines += ["— " + reason for reason in event["reasons"]]
    lines += ["— " + warning for warning in event["warnings"]]
    return "\n".join(lines)


def worker(env, st, jobs):
    """Поток разбора: берёт задания по одному и зовёт общий приём.

    Разбор идёт 15–50 секунд. Держать на нём телеграмный опрос или
    HTTP-запрос браузера нельзя — поэтому он живёт здесь, а ответ приезжает
    событием в ленту."""
    while True:
        job = jobs.get()
        try:
            events = intake.accept(env, st, job)
        except Exception as error:
            # Одно сорвавшееся задание не должно останавливать поток: иначе
            # бот замолчит навсегда, ничего об этом не сказав.
            print(f"разбор сорвался: {error}")
            events = [intake.sign({"kind": "слово",
                                   "text": "Что-то пошло не так — попробуйте ещё раз."},
                                  job)]
        try:
            for event in events:
                feed.add(event)
                if job["channel"] == "телеграм" and job.get("chat_id"):
                    say(env["bot_token"], job["chat_id"], as_text(event))
        except Exception as error:
            # И рассылка не должна останавливать поток — иначе очередь молча
            # копится, а телеграм так и не получит готовый ответ.
            print(f"рассылка события сорвалась: {error}")
        finally:
            # Сохраняем в любом случае — и когда рассылка прошла, и когда нет.
            try:
                memory.save(st)
            except Exception as error:
                # Не сохранили — поток всё равно должен продолжаться.
                print(f"не сохранил состояние: {error}")


def telegram_loop(env, st, jobs):
    """Опрос телеграма. Своим потоком, потому что главный занят страницей."""
    print("Телеграм: жду сообщений.")
    while True:
        try:
            updates = get_updates(env["bot_token"], st["offset"])
        except (requests.RequestException, RuntimeError, ValueError) as error:
            # Телеграм не отвечает — ждём и повторяем, offset не двигаем.
            print(f"телеграм не отвечает ({error}), жду пять секунд")
            time.sleep(5)
            continue
        for update in updates:
            st["offset"] = update["update_id"] + 1
            message = update.get("message")
            if message:
                try:
                    admit(env, st, jobs, message)
                except Exception as error:
                    # Одно сломанное сообщение не должно останавливать бота:
                    # offset уже сдвинут, следующее разберётся.
                    print(f"сообщение не обработалось: {error}")
            try:
                memory.save(st)
            except Exception as error:
                # Не сохранили — опрос всё равно должен продолжаться.
                print(f"не сохранил состояние: {error}")


def main():
    env = config.load_env()
    st = memory.load()
    jobs = queue.Queue()
    blocked = "api-key" if config.api_key_in_env() else ""

    if blocked:
        print(config.BLOCKED_TEXT)
        print()
    else:
        threading.Thread(target=worker, args=(env, st, jobs), daemon=True).start()
        if env["bot_token"]:
            threading.Thread(target=telegram_loop, args=(env, st, jobs),
                             daemon=True).start()
        else:
            # Это не поломка, а обычный способ работать: чеки принимает
            # браузер. Телеграм подключается в срезе 5, кнопкой.
            print("Телеграм не подключён — работаем через браузер.")

    web.quiet()
    port = web.choose_port()
    print(f"Рабочее место: http://127.0.0.1:{port}")
    print("Ctrl+C — выход.")
    try:
        web.create(env, st, jobs, blocked).run(host="127.0.0.1", port=port,
                                               threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\nОстанавливаюсь.")


if __name__ == "__main__":
    main()
