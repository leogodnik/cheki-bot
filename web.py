"""Рабочее место в браузере — второй клиент бота, наравне с телеграмом.

Здесь только маршруты. Разбор живёт в intake.py, лента — в feed.py: страница
ничего не решает сама, она показывает то же, что бот отвечает в телеграм.

Слушаем строго 127.0.0.1. Пароля у страницы нет, а показывает она токен бота
и секрет таблицы — доступ ограничен ровно тем, что адрес локальный.
"""

import logging
import socket
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_file

import agent
import config
import feed
import intake
import setup
import sheet
import state as memory
import telegram

FIRST_PORT = 8765
LAST_PORT = 8775

# Больше десяти мегабайт фотография чека не весит. Отказ до вызова агента:
# держать движок 50 секунд ради заведомо чужого файла незачем.
MAX_FILE = 10 * 1024 * 1024
PICTURES = (".jpg", ".jpeg", ".png")

# Насколько свежим считается справочник, когда человек вернулся во вкладку.
# Ушёл он туда, скорее всего, в таблицу, и вернуться мог с новой статьёй, —
# но alt-tab туда-сюда редким событием не бывает, и без нижней границы каждый
# щелчок по вкладкам поднимал бы запрос к Apps Script.
REREAD_FLOOR = 15

# Один перечитыватель справочника на весь процесс. Страница опрашивает ленту
# раз в три секунды, а таблица отвечает секунд двадцать: без замка на один
# просроченный кэш ушло бы семь запросов вместо одного.
_REREAD = threading.Lock()

# Когда к таблице ходили в последний раз — не когда прочитали. Разница важна,
# только если таблица молчит: categories_at тогда не двигается, и без этой
# отметки опрос ленты ломился бы в молчащий адрес непрерывно.
_TRIED_AT = 0.0

# Что сказать про каждый вид адреса. Тексты живут здесь, а не в setup.py:
# там разбор, здесь разговор с человеком.
ADDRESS_TROUBLE = {
    "пусто": "Пустая строка. Нужен адрес, который Google выдал после публикации.",
    "таблица": "Это адрес самой таблицы — тот, что стоит в строке браузера, "
               "когда таблица открыта. Боту нужен другой: адрес веб-приложения. "
               "Он появляется после «Развернуть → Новое развёртывание → "
               "Веб-приложение», начинается с script.google.com/macros/s/ и "
               "заканчивается на /exec. Адрес таблицы я запомнил — он пригодится "
               "для кнопки «Таблица» в рабочем месте.",
    "чужой": "Это не адрес Google Apps Script. Нужен тот, что выдало окно "
             "развёртывания: он начинается с script.google.com/macros/s/.",
    "без-exec": "Адрес почти тот, но не заканчивается на /exec. Так выглядит "
                "тестовое развёртывание (/dev) или ссылка на сам проект. Нужен "
                "адрес из окна «Развёртывание обновлено».",
}


def create(env, st, jobs, blocked=""):
    """Приложение Flask. env и st — те же словари, с которыми живёт бот."""
    app = Flask(__name__)
    # Правки в шаблонах должны быть видны после обновления страницы,
    # а не после перезапуска бота.
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    @app.get("/")
    def page():
        """Мастер или рабочее место. Решает одно: настроена ли таблица.

        Один адрес на оба состояния, а не два: человек, закрывший вкладку
        посреди установки, открывает тот же http://127.0.0.1:8765 и попадает
        туда, где остановился."""
        if config.ready(env):
            return render_template("workspace.html")
        return render_template("setup.html")

    @app.get("/photo/<name>")
    def sent_photo(name):
        """Присланная фотография — для превью в ленте.

        По ходу разбора файл переезжает из входящие/ в готово/ или спорные/,
        поэтому ищем во всех трёх: пузырь в ленте не должен гаснуть оттого,
        что бот дочитал чек.

        Из адреса берётся только последний кусок имени: «..» и подкаталоги не
        должны уводить наружу папки «чеки». Страница локальная, но отдавать
        по адресу произвольный файл с диска — не то, чем стоит рисковать."""
        safe = Path(name).name
        if Path(safe).suffix.lower() not in PICTURES:
            abort(404)
        for folder in (intake.INBOX, intake.DONE, intake.DOUBTFUL):
            path = folder / safe
            if path.is_file():
                return send_file(path)
        abort(404)

    @app.get("/api/events")
    def events():
        """Что нового в ленте после события с номером after.

        Страница зовёт этот маршрут раз в три секунды. Вебсокетов нет
        намеренно: на локальном адресе опрос дешевле и понятнее на уроке."""
        # Страница открыта — держим число статей в сайдбаре живым. Чтение
        # идёт в фоне и ответ не задерживает.
        reread_categories(env, st, sheet.CACHE_SECONDS)
        after = request.args.get("after", default=0, type=int)
        life = request.args.get("life", default="", type=str)
        fresh, last = feed.since(after, life)
        return jsonify(events=fresh, last=last, life=feed.LIFE,
                       state=snapshot(env, st, blocked))

    @app.get("/api/summary")
    def summary():
        """Состояние для мастера: тот же снимок, что едет в сайдбар.

        Отдельный маршрут, а не /api/events, потому что мастеру не нужна
        лента: событий у него нет и быть не может, а таскать их ради трёх
        строк сводки незачем."""
        return jsonify(state=snapshot(env, st, blocked))

    @app.post("/api/sheet/reread")
    def sheet_reread():
        """Перечитать справочник статей сейчас, не дожидаясь конца кэша.

        Зовёт страница, когда человек вернулся во вкладку: ушёл он обычно в
        таблицу, и вернуться мог с дописанной статьёй. Ответ уходит сразу, до
        чтения, — новое число приедет ближайшим опросом ленты."""
        reread_categories(env, st, REREAD_FLOOR)
        return jsonify(ok=True, state=snapshot(env, st, blocked))

    @app.get("/api/engines")
    def engines():
        """Что установлено. Отдельно от снимка состояния, потому что кнопка
        «Проверить снова» в мастере должна спросить заново, а не получить
        минутный кэш."""
        return jsonify(engines=agent.versions(fresh=True), titles=agent.TITLES)

    @app.get("/api/setup/script")
    def setup_script():
        """Код для Apps Script с уже подставленным секретом.

        Секрет придумывается один раз и тут же ложится в .env. Родись он
        заново на каждый заход — человек, обновивший страницу после вставки
        кода, получил бы код с другим секретом, и таблица начала бы отвечать
        «нет доступа» на ровном месте. Искать причину он будет в таблице."""
        secret = env["sheet_secret"]
        if not secret:
            secret = setup.new_secret()
            config.save_env({"SHEET_SECRET": secret})
            config.refresh_env(env)
        try:
            code = setup.script_with_secret(secret)
        except (OSError, ValueError) as error:
            return jsonify(ok=False, error=str(error))
        return jsonify(ok=True, code=code)

    @app.post("/api/setup/sheet")
    def setup_sheet():
        """Проверить адрес веб-приложения и записать его, если он рабочий."""
        url = ((request.get_json(silent=True) or {}).get("url") or "").strip()
        kind = setup.address_kind(url)

        if kind == "таблица":
            # Ошибку человека не выбрасываем: этот адрес и правда нужен — для
            # кнопки «Таблица» в сайдбаре. Кладём его туда, где он к месту, и
            # просим второй. Так путаница двух адресов не только объясняется,
            # но и оборачивается заполненной строкой в .env.
            config.save_env({"SHEET_LINK": url})
            config.refresh_env(env)

        if kind != "веб-приложение":
            return jsonify(ok=False, ready=False, error=ADDRESS_TROUBLE[kind])

        secret = env["sheet_secret"]
        if not secret:
            return jsonify(ok=False, ready=False,
                           error="Секрета ещё нет — вернитесь к коду для "
                                 "таблицы и скопируйте его заново.")
        try:
            found = sheet.fetch_categories(url, secret)
        except Exception as error:
            # Сюда приезжает и «нет доступа» от моста, и оборванная сеть, и
            # страница входа в Google вместо JSON. Текст отказа мост уже
            # сформулировал сам — передаём его как есть.
            return jsonify(ok=False, ready=False,
                           error=f"Таблица не ответила: {error}")

        # Адрес рабочий — записываем, даже если со справочником что-то не так.
        # Иначе человек, поправив A1, вставлял бы адрес заново.
        config.save_env({"SHEET_URL": url})
        config.refresh_env(env)

        # Справочник уже прочитан — кладём его в кэш, чтобы первый же чек не
        # пошёл в таблицу за тем же самым. Заодно из этого кэша сводка на
        # экране готовности и пункт «Таблица» в сайдбаре берут своё число.
        st["categories"] = found
        st["categories_at"] = time.time()
        memory.save(st)

        answer = setup.categories_verdict(found, agent.seed_categories())
        return jsonify(ok=True, ready=answer["ready"], count=answer["count"],
                       note=answer["note"])

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

    @app.post("/api/people/allow")
    def allow():
        """Впустить постучавшегося.

        Строка переезжает из «стучались» в белый список, а не копируется:
        человек не может быть в двух списках сразу, и глазами это должно быть
        видно сразу же."""
        wanted = str((request.get_json(silent=True) or {}).get("id", ""))
        settings = config.load_settings()
        knocked = settings.get("knocked", [])
        found = [person for person in knocked if str(person.get("id")) == wanted]
        if not found:
            return jsonify(ok=False,
                           error="этого человека уже нет среди стучавшихся")
        settings["knocked"] = [person for person in knocked
                               if str(person.get("id")) != wanted]
        settings["allowed"] = settings.get("allowed", []) + [{
            "id": found[0]["id"],
            "username": found[0].get("username", ""),
            "name": found[0].get("name", ""),
        }]
        # Первый впущенный — почти всегда сам хозяин: он завёл бота минуту
        # назад и написал ему сам. Имя нужно колонке «кто прислал» и
        # приветствию; спрашивать его отдельной формой значит задать вопрос,
        # ответ на который только что приехал.
        if not (settings.get("owner") or "").strip():
            settings["owner"] = found[0].get("name", "") or ""
        config.save_settings(settings)
        return jsonify(ok=True, state=snapshot(env, st, blocked))

    @app.post("/api/people/remove")
    def remove():
        """Убрать из белого списка.

        В «стучались» человека не возвращаем: он ничего не сделал, чтобы туда
        попасть заново, а строка с кнопкой «Впустить» выглядела бы как
        приглашение передумать. Напишет ещё раз — появится сам."""
        wanted = str((request.get_json(silent=True) or {}).get("id", ""))
        settings = config.load_settings()
        settings["allowed"] = [person for person in settings.get("allowed", [])
                               if str(person.get("id")) != wanted]
        config.save_settings(settings)
        return jsonify(ok=True, state=snapshot(env, st, blocked))

    @app.post("/api/engine")
    def engine():
        """Переключить движок.

        Проверяем две вещи: что такой движок вообще есть за швом и что он
        отвечает в терминале. Второе важнее: записать в settings.json движок,
        которого нет, — значит получить отказ на каждом следующем чеке, и
        человек будет искать причину в чеке."""
        wanted = (request.get_json(silent=True) or {}).get("engine", "")
        if wanted not in agent.ENGINES:
            return jsonify(ok=False, error="такого движка нет")
        if not agent.versions().get(wanted):
            return jsonify(ok=False,
                           error=f"{agent.TITLES[wanted]} не отвечает в терминале")
        settings = config.load_settings()
        settings["engine"] = wanted
        config.save_settings(settings)
        return jsonify(ok=True, state=snapshot(env, st, blocked))

    @app.post("/api/telegram/check")
    def telegram_check():
        """Спросить у телеграма, чей это токен. Ничего не сохраняем.

        Проверка отдельно от сохранения потому, что человеку показывают имя
        бота и спрашивают «это он?». Половина ошибок с токеном — вставили не
        ту строку, и увидеть это надо до того, как опрос уедет не туда."""
        token = ((request.get_json(silent=True) or {}).get("token") or "").strip()
        if not token:
            return jsonify(ok=False,
                           error="Пустая строка. Вставьте токен от @BotFather — "
                                 "длинную строку с двоеточием посередине.")
        try:
            username = telegram.check_token(token)
        except Exception as error:
            # Ловим широко нарочно: сюда приезжает и отказ телеграма, и
            # оборванная сеть, и мусор вместо JSON. Человеку во всех трёх
            # случаях нужно одно и то же — что строка не подошла.
            return jsonify(ok=False, error=f"Телеграм не принял этот токен: {error}")
        return jsonify(ok=True, username=username)

    @app.post("/api/telegram/save")
    def telegram_save():
        """Подключить бота или заменить его.

        offset сбрасывается здесь, а не в опросе, и это главное в маршруте:
        у каждого бота своя нумерация обновлений. Оставить чужой номер значит
        либо получить отказ, либо — хуже — тишину, в которой бот выглядит
        подключённым и не отвечает."""
        token = ((request.get_json(silent=True) or {}).get("token") or "").strip()
        try:
            username = telegram.check_token(token)
        except Exception as error:
            return jsonify(ok=False, error=f"Телеграм не принял этот токен: {error}")

        config.save_env({"BOT_TOKEN": token})
        config.refresh_env(env)

        settings = config.load_settings()
        settings["bot"] = username
        config.save_settings(settings)

        st["offset"] = 0
        memory.save(st)
        return jsonify(ok=True, username=username,
                       state=snapshot(env, st, blocked))

    @app.post("/api/telegram/off")
    def telegram_off():
        """Отключить телеграм. Белый список остаётся нетронутым.

        Телеграм опознаёт человека одним номером у всех ботов, и стирать
        список при отключении значило бы наказать хозяина за передумывание.
        Рабочее место без телеграма работает полностью."""
        config.save_env({"BOT_TOKEN": ""})
        config.refresh_env(env)
        st["offset"] = 0
        memory.save(st)
        return jsonify(ok=True, state=snapshot(env, st, blocked))

    return app


def reread_categories(env, st, older_than):
    """Перечитать справочник статей у таблицы, если прочитанному больше
    older_than секунд. Отдаёт запущенный поток — или None, когда идти незачем.

    Число в пункте «Таблица» — это длина последнего прочитанного справочника,
    а читал его до сих пор только разбор чека. Человек, дописавший статью в
    таблицу, видел в сайдбаре прежнее число до самого следующего чека — и
    справедливо считал, что бот его правку не заметил. Читает теперь и
    открытая страница, сама, между делом.

    Своим потоком, потому что маршрут, из которого зовут, отвечает странице
    за миллисекунды, а Apps Script — за двадцать секунд. Новое число сайдбар
    подхватит ближайшим опросом.

    Молчание таблицы и пустой лист прежний список не трогают: показать ноль
    статей из-за оборванной сети значит сказать человеку, что его справочник
    пропал."""
    global _TRIED_AT
    if not env["sheet_url"] or not env["sheet_secret"]:
        return None
    now = time.time()
    if now - max(st["categories_at"], _TRIED_AT) < older_than:
        return None
    # Не дождались замка — значит, чтение уже идёт, и второе ни к чему.
    if not _REREAD.acquire(blocking=False):
        return None
    _TRIED_AT = now

    def read():
        try:
            found = sheet.fetch_categories(env["sheet_url"], env["sheet_secret"])
            st["categories"] = found
            st["categories_at"] = time.time()
            memory.save(st)
        except Exception as error:
            print(f"справочник не перечитался ({error}) — оставляю прежний список")
        finally:
            _REREAD.release()

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    return thread


def snapshot(env, st, blocked):
    """Состояние для сайдбара. Едет с каждым ответом опроса — так сайдбар не
    может разъехаться с лентой.

    Число статей берётся из кэша в state.json, а не из таблицы: опрос идёт
    раз в три секунды, и дёргать Apps Script на каждый заход незачем. Свежесть
    этого кэша — забота reread_categories(): она перечитывает справочник в
    фоне, и снимку остаётся только назвать число."""
    settings = config.load_settings()
    return {
        "owner": (settings.get("owner") or "").strip(),
        "categories": len(st["categories"]),
        "sheet_link": env["sheet_link"],
        "engine": agent.TITLES.get(settings["engine"], settings["engine"]),
        # Ключ движка, а не название: по нему отмечается точка в переключателе.
        # Поле engine при этом остаётся названием — его читает бейдж в поле
        # ввода, и переименовать его значит без нужды тронуть чужой код.
        "engine_key": settings["engine"],
        "engines": agent.versions(),
        "titles": agent.TITLES,
        "allowed": settings.get("allowed", []),
        "knocked": settings.get("knocked", []),
        "telegram": bool(env["bot_token"]),
        "bot": (settings.get("bot") or "").strip(),
        "blocked": blocked,
    }


def published(events):
    """Ответ страницы: что появилось в ленте прямо сейчас.

    Курсор всегда 0 — не потому что лента пуста, а потому что этот ответ
    не знает, что страница уже видела. У /api/say нет своего after, в
    отличие от /api/events: попробуй мы отдать здесь номер конца ленты
    (или даже номер перед своими событиями), рисковали бы перепрыгнуть
    через чужую запись, которая легла между последним опросом страницы и
    этой отправкой, — Math.max на странице взял бы число побольше и решил
    бы, что чужое уже видено. Курсором ленты командует опрос: у него есть
    свой after, и since() отвечает по нему точно, не гадая. Цена — лишний
    заход опроса на каждую отправку, а не потерянная запись.

    Метка жизни едет и отсюда, не только из опроса: страница может узнать
    о перезапуске бота из ответа на собственную отправку, не дожидаясь
    следующего опроса."""
    return {"events": events, "last": 0, "life": feed.LIFE}


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
        # Файл повтора на диск не ложится — второй копии в папке «чеки» быть
        # не должно. Но первая копия там есть, и её имя мы помним: пузырь
        # показывает ту самую фотографию, а не имя файла.
        return [feed.add(dict(mine, photo=old.get("file") or "")), feed.add({
            "kind": "слово", "text": "Этот чек уже записан",
            "row": old.get("row"), "note": intake.when(old),
        })]

    path = intake.save_photo(data, author, Path(name).suffix.lower())
    job = {"kind": "фото", "payload": str(path), "channel": "браузер",
           "author": author, "chat_id": None, "file": path.name, "mark": mark}
    # Имя на диске, а не то, как файл звался у человека: по нему страница
    # просит превью маршрутом /photo. Имя от человека остаётся в событии на
    # случай, если файла уже нет и пузырь вернётся к подписи.
    return start(jobs, job, dict(mine, photo=path.name))


def start(jobs, job, mine):
    """Кладёт задание в очередь и рождает два события: реплику человека и
    плашку «Смотрю чек…» (или «Разбираю…» — по виду задания).

    Ответ придёт отдельным событием через 15–50 секунд — держать на нём
    HTTP-запрос нельзя, браузер оборвёт его раньше."""
    job["task"] = uuid4().hex[:8]
    born = [feed.add(mine), feed.add({"kind": "работа", "task": job["task"],
                                      "job": job["kind"]})]
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
