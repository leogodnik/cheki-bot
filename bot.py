"""Телеграм: приём сообщений, белый список, ответы.

Мозг и руки разделены. Этот файл ничего не понимает про чеки — он их
принимает, проверяет и записывает. Понимает agent.py.
"""

import json
import time

import requests

import config
import state as memory

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
    except (requests.RequestException, RuntimeError) as error:
        print(f"не смог ответить в чат {chat_id}: {error}")


def who(message):
    """Как называть человека в таблице. Ник есть не у всех, имя есть всегда."""
    sender = message.get("from", {})
    if sender.get("username"):
        return "@" + sender["username"]
    return sender.get("first_name") or "неизвестно"


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


def handle(env, st, message):
    """Пока только белый список. Разбор чеков появится в следующей задаче."""
    settings = config.load_settings()
    if message.get("from", {}).get("id") not in config.allowed_ids(settings):
        knock(env, st, message)
        return
    say(env["bot_token"], message["chat"]["id"],
        "Вижу вас. Чеки научусь разбирать в следующей задаче.")


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
                    handle(env, st, message)
                except Exception as error:
                    # Одно сломанное сообщение не должно останавливать бота:
                    # offset уже сдвинут, следующее разберётся.
                    print(f"сообщение не обработалось: {error}")
            memory.save(st)


if __name__ == "__main__":
    main()
