"""Единый вход разбора. Телеграм и браузер зовут отсюда одно и то же.

Это и есть то место, ради которого затевалось рабочее место: разбор, проверки
без модели, запись в таблицу и раскладка файлов живут здесь, и обойти их
нельзя ни одним из двух путей. Каналы отличаются только тем, как человек
прислал сообщение и как ему ответить, — а не тем, что с сообщением сделают.

Ответа отсюда никто не печатает: функция возвращает события. Словами их
подаёт bot.py — в чат, словарями web.py — в браузер. Одно событие, две подачи.
"""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

import requests

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

    # Проверка стоит здесь, а не только при получении. «Убрал» обязано значить
    # «больше не пишет в мою таблицу», иначе кнопка обманывает. Цена — одна
    # проверка в начале разбора; выгода — кнопка означает то, что написано.
    if job["channel"] == "телеграм" and \
            job.get("user_id") not in config.allowed_ids(settings):
        return [sign({"kind": "слово", "text": "Больше не записываю.",
                      "note": "Хозяин таблицы закрыл доступ."}, job)]

    events = []

    # Отложенные строки уезжают при первой возможности — раньше, чем новая.
    delivered = sheet.flush(st, env["sheet_url"], env["sheet_secret"])
    if delivered:
        events.append({"kind": "слово",
                       "text": f"Отложенные строки доехали до таблицы: {delivered}."})

    categories, source = sheet.categories(st, env["sheet_url"], env["sheet_secret"])
    if not categories:
        # Придумывать статьи агенту нельзя: в отчёте заведутся «Продукты»,
        # «Продукты питания» и «Еда» вместо одной строки. Но причина пустого
        # списка бывает разной: лист правда пуст или переименован — либо
        # таблица просто не успела ответить. Это не одно и то же, и второе
        # не повод посылать человека чинить лист, который цел.
        if source == "молчит":
            events.append({
                "kind": "слово",
                "text": "Таблица не отвечает — разбирать не буду.",
                "note": "Попробуйте ещё раз через минуту.",
            })
        else:
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
        if path:
            # Фотография правкой не бывает: так агент отвечает, когда на
            # снимке не чек. Ведём себя как с «не расход» — файл в спорные,
            # человеку честный ответ.
            move(path, DOUBTFUL)
            events.append({"kind": "слово", "text": "На фотографии не вижу расхода.",
                           "note": "Правку пришлите текстом: «не 450, а 480»."})
        else:
            events += fix(env, st, job, categories, today, settings["engine"])
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
        memory.remember(st, job["mark"], number, path.name if path else "")

    # Запомнили, что записали последним: из этого потом делается правка.
    # Помним и строку, не доехавшую до таблицы (number is None) — иначе
    # «не 450, а 480» уехало бы в предыдущую, давно записанную строку.
    memory.remember_last(st, memory.address(job["channel"], job["author"]), {
        "row": number,
        "fields": row,
        # Канал и автор лежат здесь не для адресации — адрес уже посчитан.
        # Они нужны, чтобы сказать человеку, чью строку он пытается поправить.
        "channel": job["channel"],
        "author": job["author"],
    })

    events.append({
        "kind": "запись",
        "merchant": answer["merchant"],
        "amount": amount,
        "currency": answer["currency"],
        "category": verdict["category"],
        # Чем разобрано. Не ключ, а название: событие уезжает и в чат, и в
        # браузер, и там и там его читает человек.
        "engine": agent.TITLES.get(settings["engine"], settings["engine"]),
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


def fix(env, st, job, categories, today, engine):
    """Правка последней записи. Возвращает события ленты.

    Ответ первого разбора сюда не передаётся: из него взято одно — намерение.
    Здесь агент зовётся второй раз, уже вместе с прошлой записью."""
    here = memory.address(job["channel"], job["author"])
    spot, fresh = memory.newest(st)

    # В браузере лента общая: внизу может стоять запись из телеграма, и «не
    # 450, а 480» тогда скорее всего про неё. Молча поправить вместо неё свою
    # прошлую строку — худшее, что тут можно сделать, поэтому отказываем и
    # показываем, чья это строка.
    #
    # В телеграме ровно наоборот: человек видит только свой чат, чужих записей
    # для него не существует, и отказ по строке, которой он не видел, выглядел
    # бы поломкой. Поэтому проверка на самую свежую запись — только для
    # браузера, а память по каналам работает в обоих.
    if job["channel"] == "браузер" and fresh and spot != here:
        line = (f"строка {fresh['row']}" if fresh["row"]
                else "запись, ещё не доехавшая до таблицы")
        return [{
            "kind": "слово",
            "text": f"Не трогаю: последняя запись не ваша — {line}, "
                    f"{fresh['author']} · {fresh['channel']}.",
            "note": "Правлю только то, что записано в этом же окне. "
                    "Чужую строку поправьте в таблице руками.",
        }]

    mine = memory.last(st, here)
    if mine is None:
        return [{"kind": "слово", "text": "Пока нечего править — я ещё ничего не записывал.",
                 "note": "Пришлите трату, а поправить её можно следующим сообщением."}]
    if mine["row"] is None:
        # Строка ушла в очередь и номера у неё пока нет. Править по номеру
        # соседней строки нельзя — там чужой расход.
        return [{"kind": "слово",
                 "text": "Последняя запись ещё не доехала до таблицы — править нечего.",
                 "note": "Она уедет сама, когда таблица ответит. Тогда и поправим."}]

    old = mine["fields"]
    try:
        answer = agent.parse("текст", rework(old, job["payload"]), categories,
                             today, engine)
    except agent.AgentError as error:
        print(f"агент не справился с правкой: {error}")
        return [{"kind": "слово", "text": "Не смог разобрать правку.",
                 "note": "Напишите, что поправить: «не 450, а 480»."}]

    if answer["intent"] != "правка":
        # Увидев прошлую запись, агент передумал: это не правка, а новая
        # трата. Дописать её отсюда нельзя — путь записи в проекте один, и он
        # в accept(); второго такого пути заводить не будем.
        return [{"kind": "слово", "text": "Это похоже не на правку, а на новую трату.",
                 "note": "Пришлите её отдельным сообщением."}]

    # Проверки без модели те же самые: правка — такая же запись, и дата из
    # будущего в ней ловится так же. Статус пересчитывается, и это важно в обе
    # стороны: продиктованная сумма снимает с строки пометку «проверить», а
    # правка, испортившая дату, эту пометку ставит.
    verdict = checks.review(answer, categories, today)
    amount = answer["amount"] if checks.is_number(answer["amount"]) else ""

    # Новая запись собирается из старой: source, who и file остаются как были.
    # Поэтому дифф их и не увидит — не потому, что мы их из него выкинули.
    new = dict(old,
               date=answer["date"],
               amount=amount,
               currency=answer["currency"],
               merchant=answer["merchant"],
               category=verdict["category"],
               payment=answer["payment"],
               status=verdict["status"])

    changes = diff(old, new)
    if not changes:
        # Мост на такой запрос ответил бы «в правке не пришло ни одного поля
        # строки: менять нечего» — правильный отказ, но человеку он не про то.
        # Запрос, отказ которого известен заранее, лучше не посылать.
        return [{"kind": "слово",
                 "text": f"Ничего не изменилось — строка {mine['row']} и так такая.",
                 "note": answer["reply"]}]

    try:
        changed = sheet.edit_row(env["sheet_url"], env["sheet_secret"],
                                 mine["row"], old["merchant"], old["amount"],
                                 changes)
    except sheet.SheetError as error:
        # Отказ моста написан для человека — передаём его дословно. «Строка 48
        # изменилась: ожидались „Пятёрочка“ и 450, а в таблице „Магнит“ и 980»
        # понятнее всего, что мы могли бы сочинить вместо него: по этой фразе
        # видно, куда уехала строка.
        print(f"таблица не приняла правку: {error}")
        return [{"kind": "слово", "text": f"Не поправил строку {mine['row']}.",
                 "note": str(error)}]
    except requests.RequestException as error:
        # А это написано для программиста: «HTTPSConnectionPool… Max retries
        # exceeded» человеку не говорит ничего. В терминал — как есть, в ленту
        # — своими словами.
        print(f"таблица не ответила на правку: {error}")
        return [{"kind": "слово",
                 "text": f"Таблица не ответила — строка {mine['row']} осталась прежней.",
                 "note": "Очереди у правки нет, попробуйте ещё раз."}]

    # Поправленная строка снова становится последней, и по времени тоже:
    # следующее «нет, 500» ляжет на неё же, а не на ту, что была до правки.
    memory.remember_last(st, here, dict(mine, fields=new))

    # Фраза строится по changed из ответа таблицы, а не по нашему changes:
    # в ленте должно стоять то, что таблица подтвердила.
    event = {"kind": "слово", "text": retell(changed, old, new), "row": mine["row"]}
    trouble = verdict["reasons"] + verdict["warnings"]
    if trouble:
        event["note"] = "; ".join(trouble)
    return [event]


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


# Что из записи агент вправе поправить. Остальные четыре поля — source, who,
# file и status — говорят, откуда взялась строка и что с ней сделали проверки.
# Правкой они не меняются, и показать их агенту значило бы позвать его их менять.
EDITABLE = ("date", "amount", "currency", "merchant", "category", "payment")


def rework(old, message):
    """Задание агенту на правку: прошлая запись плюс слова человека.

    Отдельного входа для правки в agent.parse() нет намеренно. Правка — это
    сообщение текстом, к которому приложена прошлая запись; шов между ботом и
    движком от этого не меняется, и оба движка продолжают работать без единой
    правки в agent.py и engines/.

    Строчная буква в начале не опечатка: agent.build_task() ставит перед этим
    текстом «Разбери сообщение о расходе:», и фраза продолжает его."""
    known = {name: old.get(name) for name in EDITABLE}
    return ("человек поправляет уже записанную трату. Вот она целиком: "
            + json.dumps(known, ensure_ascii=False)
            + f". Человек пишет: «{message}». Верни эту же запись с "
              "исправлениями — поля, которых правка не касается, оставь как были.")


def same(before, after):
    """Одно ли это значение.

    Числа сравниваются как числа: 450 и 450.0 — одна и та же сумма. Пустая
    клетка и None — тоже одно: в таблицу они уезжают одинаково, и объявить их
    разными значило бы каждый раз стирать пустую клетку заново."""
    if checks.is_number(before) and checks.is_number(after):
        return float(before) == float(after)
    if before in ("", None) and after in ("", None):
        return True
    return before == after


def diff(old, new):
    """Что изменилось: словарь только из изменившихся полей.

    Это обязанность питоновской стороны, и ничьей другой. Мост перечисляет в
    ответном поле changed всё, что получил, и с прежним значением не сравнивает
    — это не его дело. Пошлём поле, которое не менялось, — мост честно вернёт
    его в changed, и лента расскажет про правку, которой не было.

    Никаких исключений по именам полей здесь нет: происхождение строки не
    попадает в дифф не потому, что мы его отсюда выкинули, а потому, что новая
    запись собирается из старой и эти поля в ней те же самые."""
    return {name: new[name] for name in new if not same(old.get(name), new[name])}


# Имена колонок человеческими словами, в винительном падеже: «Поправил сумму».
# Ключи латиницей — это имена полей протокола, значения русские, как в схеме.
LABELS = {
    "date": "дату", "amount": "сумму", "currency": "валюту",
    "merchant": "продавца", "category": "статью", "payment": "способ оплаты",
    "source": "источник", "who": "автора", "status": "пометку", "file": "файл",
}


def look(value):
    """Значение словами для ленты.

    480.0 — это «480»: хвостовой ноль в сумме читается как копейки, которых
    не было. Пустая клетка — «пусто», иначе фраза «Поправил продавца:  → Магнит»
    выглядит как поломка, а не как правка."""
    if checks.is_number(value):
        return str(int(value)) if float(value) == int(value) else f"{value:.2f}"
    if value is None or not str(value).strip():
        return "пусто"
    return str(value)


def retell(changed, old, new):
    """«Поправил сумму: 450 → 480».

    Список changed берётся из ответа моста, а не из нашего диффа: в ленте должно
    стоять то, что таблица подтвердила, а не то, что мы собирались сделать.
    Незнакомое имя поля не роняет фразу — показываем его как есть: лучше
    непонятное слово в ленте, чем исключение вместо ответа."""
    parts = []
    for name in changed:
        parts.append(f"{LABELS.get(name, name)}: "
                     f"{look(old.get(name))} → {look(new.get(name))}")
    if not parts:
        return "Поправил строку"
    return "Поправил " + ", ".join(parts)
