"""Рабочее место в браузере — второй клиент бота, наравне с телеграмом.

Здесь только маршруты. Разбор живёт в intake.py, лента — в feed.py: страница
ничего не решает сама, она показывает то же, что бот отвечает в телеграм.

Слушаем строго 127.0.0.1. Пароля у страницы нет, а показывает она токен бота
и секрет таблицы — доступ ограничен ровно тем, что адрес локальный.
"""

import logging
import socket
import sys

from flask import Flask, jsonify, render_template, request

import feed

FIRST_PORT = 8765
LAST_PORT = 8775


def create(env, st, jobs, blocked=""):
    """Приложение Flask. env и st — те же словари, с которыми живёт бот."""
    app = Flask(__name__)

    @app.get("/")
    def page():
        return render_template("workspace.html")

    @app.get("/api/events")
    def events():
        """Что нового в ленте после события с номером after.

        Страница зовёт этот маршрут раз в три секунды. Вебсокетов нет
        намеренно: на локальном адресе опрос дешевле и понятнее на уроке."""
        after = request.args.get("after", default=0, type=int)
        fresh, last = feed.since(after)
        return jsonify(events=fresh, last=last, state=snapshot(env, st, blocked))

    return app


def snapshot(env, st, blocked):
    """Состояние для сайдбара. Наполнится в задаче 9."""
    return {}


def choose_port():
    """Первый свободный порт из 8765…8775.

    Занятый порт — обычное дело: бот уже запущен в соседнем окне терминала.
    Падать из-за этого незачем, но и молча уезжать на другой адрес нельзя —
    поэтому выбранный адрес печатается в терминал."""
    for port in range(FIRST_PORT, LAST_PORT + 1):
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            probe.close()
    sys.exit(f"Порты {FIRST_PORT}…{LAST_PORT} заняты — закройте лишнее "
             "и запустите бота заново.")


def quiet():
    """Flask печатает строку на каждый запрос, а страница опрашивает ленту
    раз в три секунды. В терминале должно быть видно бота, а не журнал
    веб-сервера."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
