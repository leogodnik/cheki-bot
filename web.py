"""Рабочее место в браузере — второй клиент бота, наравне с телеграмом.

Здесь только маршруты. Разбор живёт в intake.py, лента — в feed.py: страница
ничего не решает сама, она показывает то же, что бот отвечает в телеграм.

Слушаем строго 127.0.0.1. Пароля у страницы нет, а показывает она токен бота
и секрет таблицы — доступ ограничен ровно тем, что адрес локальный.
"""

import logging
import socket
import sys
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

import agent
import config
import feed
import intake

FIRST_PORT = 8765
LAST_PORT = 8775

# Больше десяти мегабайт фотография чека не весит. Отказ до вызова агента:
# держать движок 50 секунд ради заведомо чужого файла незачем.
MAX_FILE = 10 * 1024 * 1024
PICTURES = (".jpg", ".jpeg", ".png")


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
        if blocked:
            return jsonify(published([feed.add({
                "kind": "слово", "text": "Бот не запущен.",
                "note": "Уберите ANTHROPIC_API_KEY из окружения и запустите заново.",
            })]))

        settings = config.load_settings()
        author = owner_name(settings)

        upload = request.files.get("file")
        if upload and upload.filename:
            return jsonify(published(photo(st, jobs, upload, author)))

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
    """Состояние для сайдбара. Едет с каждым ответом опроса — так сайдбар не
    может разъехаться с лентой.

    Число статей берётся из кэша в state.json, а не из таблицы: опрос идёт
    раз в три секунды, и дёргать Apps Script на каждый заход незачем."""
    settings = config.load_settings()
    return {
        "owner": (settings.get("owner") or "").strip(),
        "categories": len(st["categories"]),
        "sheet_link": env["sheet_link"],
        "engine": agent.TITLES.get(settings["engine"], settings["engine"]),
        "telegram": bool(env["bot_token"]),
        "blocked": blocked,
    }


def published(events):
    """Ответ страницы: что появилось в ленте прямо сейчас.

    Курсор — номер последнего события всей ленты, а не только этих двух: за
    те же секунды в ленту мог попасть чужой чек из телеграма, и следующий
    опрос обязан его увидеть. Номер своих последних событий для этого не
    годится — он их не пропустит. Своих же событий страница при этом не
    покажет второй раз: их номера в любом случае не больше номера ленты."""
    _, last = feed.since(0)
    return {"events": events, "last": last}


def photo(st, jobs, upload, author):
    """Фотография из браузера: проверить, поймать повтор, положить в очередь.

    Дедупликация в браузере устроена не так, как в телеграме: там файл
    опознаёт сам Bot API по file_unique_id, здесь такого нет — считаем хеш
    содержимого. Считаем до того, как файл лёг на диск: повтор не должен
    плодить копии в чеки/входящие/."""
    name = upload.filename
    mine = {"kind": "мой", "file": name}

    if Path(name).suffix.lower() not in PICTURES:
        return [feed.add(mine), feed.add({
            "kind": "слово", "text": "Это не фотография чека.",
            "note": "Перетащите файл JPG или PNG.",
        })]

    data = upload.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        return [feed.add(mine), feed.add({
            "kind": "слово", "text": "Файл больше 10 МБ.",
            "note": "Уменьшите фотографию и пришлите ещё раз.",
        })]

    mark = intake.fingerprint(data)
    old = intake.duplicate(st, mark)
    if old:
        return [feed.add(mine), feed.add({
            "kind": "слово", "text": "Этот чек уже записан",
            "row": old.get("row"), "note": intake.when(old),
        })]

    path = intake.save_photo(data, author, Path(name).suffix.lower())
    job = {"kind": "фото", "payload": str(path), "channel": "браузер",
           "author": author, "chat_id": None, "file": path.name, "mark": mark}
    return start(jobs, job, mine)


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
