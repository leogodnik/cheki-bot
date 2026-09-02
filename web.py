"""Рабочее место в браузере — второй клиент бота, наравне с телеграмом.

Здесь только маршруты. Разбор живёт в intake.py, лента — в feed.py: страница
ничего не решает сама, она показывает то же, что бот отвечает в телеграм.

Слушаем строго 127.0.0.1. Пароля у страницы нет, а показывает она токен бота
и секрет таблицы — доступ ограничен ровно тем, что адрес локальный.
"""

import logging
import socket
import sys
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

import config
import feed
import intake

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

    @app.post("/api/say")
    def say():
        """Приём из браузера: фотография или текст.

        Отказы возвращаются не кодом ошибки, а событием ленты: у человека
        один список того, что произошло, и отказ — такая же его строка,
        как запись."""
        settings = config.load_settings()
        author = owner_name(settings)

        text = (request.form.get("text") or "").strip()
        if not text:
            return jsonify(published([feed.add({
                "kind": "слово",
                "text": "Пустое сообщение — нечего разбирать.",
                "note": "Напишите тратой или перетащите чек.",
            })]))

        job = {"kind": "текст", "payload": text, "channel": "браузер",
               "author": author, "chat_id": None, "file": "", "mark": ""}
        return jsonify(published(start(jobs, job, {"kind": "мой", "text": text})))

    return app


def snapshot(env, st, blocked):
    """Состояние для сайдбара. Наполнится в задаче 9."""
    return {}


def published(events):
    """Ответ страницы: что появилось в ленте прямо сейчас.

    Номер последнего события отдаётся вместе с ними, чтобы страница не
    показала эти же события второй раз следующим опросом."""
    return {"events": events, "last": events[-1]["id"] if events else 0}


def start(jobs, job, mine):
    """Кладёт задание в очередь и рождает два события: реплику человека и
    плашку «Смотрю чек…».

    Ответ придёт отдельным событием через 15–50 секунд — держать на нём
    HTTP-запрос нельзя, браузер оборвёт его раньше."""
    job["task"] = uuid4().hex[:8]
    born = [feed.add(mine), feed.add({"kind": "работа", "task": job["task"]})]
    jobs.put(job)
    return born


def owner_name(settings):
    """Как подписывать записи из браузера в колонке «кто прислал».

    Имени нет — «хозяин»: пустая клетка в таблице хуже, чем общее слово."""
    return (settings.get("owner") or "").strip() or "хозяин"


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
