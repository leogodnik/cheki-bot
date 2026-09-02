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
    # Тело читаем прежде, чем смотреть на код ответа, и raise_for_status()
    # не зовём. Её текст выглядит так: «404 Client Error: Not Found for url:
    # https://api.telegram.org/bot<ТОКЕН>/getMe» — и он показывается человеку
    # на странице, в плашке «Телеграм не принял этот токен». Читать там
    # нечего, зато токен, который человек только что вставил, уезжает
    # обратно на экран. У телеграма на этот случай есть своё слово: он
    # отвечает JSON-ом с description и на отказе тоже.
    try:
        answer = response.json()
    except ValueError:
        raise RuntimeError(f"телеграм ответил не по-человечески "
                           f"(код {response.status_code})")
    if not answer.get("ok"):
        raise RuntimeError(answer.get("description")
                           or f"телеграм отказал (код {response.status_code})")
    return answer["result"]


def check_token(token):
    """Чей это токен. Возвращает ник бота или поднимает исключение.

    Ник нужен человеку, а не программе: он вставил длинную строку и должен
    увидеть, что она от того бота, которого завёл минуту назад, а не от
    прошлогоднего. Токен от чужого бота, вставленный по ошибке, ловится
    здесь — до того, как опрос уедет не туда."""
    return call(token, "getMe").get("username", "")
