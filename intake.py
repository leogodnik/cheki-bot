"""Единый вход разбора. Телеграм и браузер зовут отсюда одно и то же.

Это и есть то место, ради которого затевалось рабочее место: разбор, проверки
без модели, запись в таблицу и раскладка файлов живут здесь, и обойти их
нельзя ни одним из двух путей. Каналы отличаются только тем, как человек
прислал сообщение и как ему ответить, — а не тем, что с сообщением сделают.

Ответа отсюда никто не печатает: функция возвращает события. Словами их
подаёт bot.py — в чат, словарями web.py — в браузер. Одно событие, две подачи.
"""

import hashlib
from datetime import date, datetime
from pathlib import Path

import agent
import checks
import config
import sheet
import state as memory

BASE_DIR = Path(__file__).resolve().parent
INBOX = BASE_DIR / "чеки" / "входящие"
DONE = BASE_DIR / "чеки" / "готово"
DOUBTFUL = BASE_DIR / "чеки" / "спорные"


def accept(env, st, job):
    """Путь сообщения от входа до строки в таблице. Возвращает события ленты."""
    settings = config.load_settings()
    events = []

    # Отложенные строки уезжают при первой возможности — раньше, чем новая.
    delivered = sheet.flush(st, env["sheet_url"], env["sheet_secret"])
    if delivered:
        events.append({"kind": "слово",
                       "text": f"Отложенные строки доехали до таблицы: {delivered}."})

    categories, source = sheet.categories(st, env["sheet_url"], env["sheet_secret"])
    if not categories:
        # Придумывать статьи агенту нельзя: в отчёте заведутся «Продукты»,
        # «Продукты питания» и «Еда» вместо одной строки.
        events.append({
            "kind": "слово",
            "text": "Не вижу справочник статей в таблице — разбирать не буду.",
            "note": "Иначе в отчёте заведутся выдуманные статьи. "
                    "Проверьте лист «Статьи».",
        })
        return [sign(event, job) for event in events]
    if source == "запас":
        events.append({
            "kind": "слово",
            "text": "Таблица не отдала справочник, работаю по последнему "
                    "известному списку статей.",
        })

    today = date.today()
    try:
        answer = agent.parse(job["kind"], job["payload"], categories, today,
                             settings["engine"])
    except agent.AgentError as error:
        # Файл остаётся во входящих: сам он не пересмотрится, второй раз
        # чек присылает человек.
        print(f"агент не справился: {error}")
        events.append({"kind": "слово", "text": "Не смог разобрать.",
                       "note": "Попробуйте ещё раз или напишите текстом."})
        return [sign(event, job) for event in events]

    path = Path(job["payload"]) if job["kind"] == "фото" else None

    if answer["intent"] == "правка":
        # Правка последней записи появится в срезе 3. Пока честно говорим,
        # что не умеем, и ничего не пишем: молча проглотить исправление
        # хуже, чем отказать.
        if path:
            move(path, DOUBTFUL)
        events.append({"kind": "слово", "text": "Правки пока не умею.",
                       "note": "Пришлите трату заново, целиком."})
        return [sign(event, job) for event in events]

    if answer["intent"] == "не расход":
        # В таблицу не пишем вообще. Файл не помечаем разобранным: если это
        # было меню, человек может прислать настоящий чек тем же файлом.
        if path:
            move(path, DOUBTFUL)
        events.append({"kind": "слово", "text": answer["reply"]})
        return [sign(event, job) for event in events]

    verdict = checks.review(answer, categories, today)
    if path:
        path = move(path, DONE if verdict["status"] == "готово" else DOUBTFUL)

    amount = answer["amount"] if checks.is_number(answer["amount"]) else None
    row = {
        "date": answer["date"],
        "amount": amount if amount is not None else "",
        "currency": answer["currency"],
        "merchant": answer["merchant"],
        "category": verdict["category"],
        "payment": answer["payment"],
        "source": "фото чека" if job["kind"] == "фото" else "текст",
        # Канала в таблице нет намеренно: иначе сводная по людям разложит
        # одного человека на две строки.
        "who": job["author"],
        "status": verdict["status"],
        "file": path.name if path else "",
    }
    number = sheet.deliver(st, env["sheet_url"], env["sheet_secret"], row)
    if job.get("mark"):
        memory.remember(st, job["mark"], number)

    events.append({
        "kind": "запись",
        "merchant": answer["merchant"],
        "amount": amount,
        "currency": answer["currency"],
        "category": verdict["category"],
        "payment": answer["payment"],
        "date": answer["date"],
        "row": number,
        "status": verdict["status"],
        "reasons": verdict["reasons"],
        "warnings": verdict["warnings"],
        # Фраза агента нужна телеграму: там ответ это текст. Страница её не
        # берёт — она собирает строку из полей сама, иначе суммы в сайдбаре
        # не встанут колонкой.
        "reply": answer["reply"],
        "file": path.name if path else "",
    })
    return [sign(event, job) for event in events]


def sign(event, job):
    """Подпись под событием.

    Чужое подписывается «Мария · телеграм» — человек впереди способа: значимо,
    кто потратил, а не с какого устройства прислал. Своё, сделанное здесь же,
    не подписывается вовсе: подпись означает «это не вы»."""
    if job["channel"] != "браузер":
        event = dict(event, author=job["author"], channel=job["channel"])
    if job.get("task"):
        # По номеру задачи страница уберёт плашку «Смотрю чек…».
        event = dict(event, task=job["task"])
    return event


def fingerprint(data):
    """Отпечаток файла. В телеграме такой даёт сам Bot API — file_unique_id,
    в браузере его нет, поэтому считаем хеш содержимого."""
    return hashlib.sha256(data).hexdigest()


def duplicate(st, mark):
    """Этот чек уже разбирали? Отдаёт запомненное или None."""
    return memory.seen(st, mark)


def when(old):
    """«такой же файл приходил сегодня в 11:20» — чтобы человек понял, о чём
    речь, а не гадал, когда это было."""
    moment = datetime.fromtimestamp(old.get("at") or 0)
    when_day = "сегодня" if moment.date() == date.today() else moment.strftime("%d.%m")
    return f"такой же файл приходил {when_day} в {moment:%H:%M}"


def safe(name):
    """Имя в имя файла: буквы и цифры оставляем, остальное — подчёркивание."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")
    return cleaned or "кто-то"


def save_photo(data, author, suffix=".jpg"):
    """Кладёт фотографию в чеки/входящие/ и отдаёт путь.

    Имя одно на оба канала: дата, время и кто прислал."""
    INBOX.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = INBOX / f"{stamp}_{safe(author)}{suffix}"
    path.write_bytes(data)
    return path


def move(path, folder):
    """Файл едет в готово/ только при статусе «готово», иначе в спорные/."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    path.replace(target)
    return target
