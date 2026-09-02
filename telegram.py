"""Разговор с Bot API — то немногое из телеграма, что нужно и боту, и странице.

Отдельным файлом этот кусок стал, когда токен начали подключать из браузера:
маршрут «проверить токен» спрашивает у телеграма getMe, а импортировать ради
этого bot.py нельзя — bot.py сам импортирует web.py, и вышло бы кольцо.

Здесь только вызов метода и вопрос «чей это токен». Приём сообщений, белый
список и ответы остались в bot.py: они про бота, а не про протокол.
"""

import requests

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


def check_token(token):
    """Чей это токен. Возвращает ник бота или поднимает исключение.

    Ник нужен человеку, а не программе: он вставил длинную строку и должен
    увидеть, что она от того бота, которого завёл минуту назад, а не от
    прошлогоднего. Токен от чужого бота, вставленный по ошибке, ловится
    здесь — до того, как опрос уедет не туда."""
    return call(token, "getMe").get("username", "")
