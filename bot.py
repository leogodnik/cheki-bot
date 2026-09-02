"""Телеграм: приём сообщений, белый список, ответы.

Мозг и руки разделены. Этот файл ничего не понимает про чеки — он их
принимает и кладёт в очередь на разбор, а ответ агента подаёт словами в чат.
Разбор — общий для обоих каналов, он живёт в intake.py.
"""

import queue
import threading
import time

import requests

import config
import feed
import intake
import state as memory
import web
from telegram import POLL_SECONDS, call


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


def knock(env, message):
    """Чужому отвечаем один раз и запоминаем его в «стучались».

    Настройки перечитываются здесь заново, хотя вызывающий их уже читал:
    между тем чтением и этой строкой хозяин мог нажать «Впустить», и тогда
    человеку незачем слышать отказ.

    Числовой id хранится, но на экран не попадает никогда: показываем ник, а
    если ника нет — имя из профиля и пометку. Ник в телеграме заводить
    необязательно, и человек без ника не должен выглядеть сломанной строкой."""
    sender = message.get("from", {})
    sender_id = sender.get("id")
    settings = config.load_settings()
    if sender_id in config.allowed_ids(settings):
        return
    knocked = settings.get("knocked", [])
    if any(str(person.get("id")) == str(sender_id) for person in knocked):
        return
    knocked.append({"id": sender_id,
                    "username": sender.get("username", ""),
                    "name": sender.get("first_name", ""),
                    "at": time.time()})
    settings["knocked"] = knocked
    config.save_settings(settings)
    print(f"постучался чужой: {who(message)} — впустите его в сайдбаре, "
          "раздел «Доступ»")
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
        knock(env, message)
        return

    incoming = extract(message)
    if incoming is None:
        tell(env, chat_id, {"kind": "слово",
                            "text": "Пришлите фотографию чека или напишите "
                            "тратой: что, сколько и чем платили.",
                            "note": "Например: обед 850 картой",
                            "author": author, "channel": "телеграм"})
        return

    if incoming["kind"] == "голос":
        tell(env, chat_id, {"kind": "слово", "text": "Голосовые не умею.",
                            "note": "напишите текстом или пришлите фото чека",
                            "author": author, "channel": "телеграм"})
        return

    job = {"kind": incoming["kind"], "payload": "", "channel": "телеграм",
           "author": author, "chat_id": chat_id,
           # Идентификатор нужен разбору: он проверит белый список ещё раз,
           # уже перед вызовом движка.
           "user_id": message.get("from", {}).get("id"),
           "file": "", "mark": "", "task": ""}

    if incoming["kind"] == "фото":
        mark = incoming["photo"]["file_unique_id"]
        old = intake.duplicate(st, mark)
        if old:
            tell(env, chat_id, {"kind": "слово", "text": "Этот чек уже записан",
                                "row": old.get("row"), "note": intake.when(old),
                                "author": author, "channel": "телеграм"})
            return
        try:
            path = download_photo(env["bot_token"], incoming["photo"], author)
        except (requests.RequestException, RuntimeError) as error:
            print(f"не скачал фотографию: {error}")
            tell(env, chat_id, {"kind": "слово", "text": "Не смог скачать фотографию.",
                                "note": "Пришлите ещё раз.",
                                "author": author, "channel": "телеграм"})
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
    """Надзор за опросом. Живёт всё время работы бота, даже когда токена нет.

    Поток стартует всегда, в том числе с пустым .env: токен может появиться
    через минуту — из мастера или из сайдбара, — и человек не должен ради
    этого перезапускать бота.

    Две секунды сна вместо тридцати не расточительство: пустая проверка стоит
    одно сравнение строк, а полминуты ожидания после нажатия «Подключить»
    человек прочтёт как поломку."""
    while True:
        token = env["bot_token"]
        if not token:
            time.sleep(2)
            continue
        print("Телеграм: жду сообщений.")
        poll_with(env, st, jobs, token)
        print("Телеграм: опрос остановлен — бота заменили или отключили.")


def poll_with(env, st, jobs, token):
    """Опрос телеграма одним конкретным токеном. Своим потоком, потому что
    главный занят страницей."""
    while True:
        try:
            updates = get_updates(token, st["offset"])
        except (requests.RequestException, RuntimeError, ValueError) as error:
            # Телеграм не отвечает — ждём и повторяем, offset не двигаем.
            print(f"телеграм не отвечает ({error}), жду пять секунд")
            time.sleep(5)
            continue
        # Пока висел долгий опрос, бота могли заменить. Эти обновления от
        # прежнего бота, и двигать по ним offset нового нельзя: у каждого бота
        # своя нумерация, и чужой номер новый бот либо не поймёт, либо поймёт
        # неправильно и промолчит.
        if env["bot_token"] != token:
            return
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
        # Поток заводится всегда, даже без токена: решает уже надзор внутри.
        # Токен может появиться через минуту — из сайдбара или из мастера, — и
        # перезапускать ради этого бота человек не должен.
        threading.Thread(target=telegram_loop, args=(env, st, jobs),
                         daemon=True).start()
        if not env["bot_token"]:
            # Это не поломка, а обычный способ работать: чеки принимает
            # браузер. Телеграм подключается кнопкой в сайдбаре.
            print("Телеграм не подключён — работаем через браузер.")

    web.quiet()
    port = web.choose_port()
    if config.ready(env):
        print(f"Рабочее место: http://127.0.0.1:{port}")
    else:
        print(f"Настройка: http://127.0.0.1:{port}")
        print("Таблица ещё не подключена — открою мастер.")
    print("Ctrl+C — выход.")
    try:
        web.create(env, st, jobs, blocked).run(host="127.0.0.1", port=port,
                                               threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\nОстанавливаюсь.")


if __name__ == "__main__":
    main()
