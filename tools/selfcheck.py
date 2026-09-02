"""Самопроверка чистых функций — тех, где тихая опечатка даёт кривые строки
в таблице.

Запуск: .venv/bin/python tools/selfcheck.py

Это не тесты проекта. Проект проверяется живьём, чеками и ботом, как написано
в спеке. Здесь только то, что можно проверить без телеграма, таблицы и модели:
служебная память и проверки без модели.
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import checks
import config
import feed
import intake
import sheet
import state
import web

passed = 0
failed = []


def check(name, ok):
    global passed
    if ok:
        passed += 1
        print("  ✓", name)
    else:
        failed.append(name)
        print("  ✗", name)


print("служебная память")
with tempfile.TemporaryDirectory() as folder:
    state.STATE_PATH = Path(folder) / "state.json"

    check("пустого файла нет — отдаём заготовку", state.load() == state.EMPTY)

    memory = state.load()
    memory["offset"] = 42
    state.save(memory)
    check("offset переживает перезапуск", state.load()["offset"] == 42)

    state.STATE_PATH.write_text("{это не json", encoding="utf-8")
    check("испорченный файл не роняет бота", state.load() == state.EMPTY)

    memory = state.load()
    state.remember(memory, "AgAD123", 47)
    check("файл запоминается вместе с номером строки",
          state.seen(memory, "AgAD123")["row"] == 47)
    check("чужой файл не считается разобранным",
          state.seen(memory, "AgAD999") is None)
    state.remember(memory, "AgAD777", None)
    check("строка без номера тоже запоминается",
          state.seen(memory, "AgAD777")["row"] is None)

    state.remember(memory, "AgAD555", 48, "2026-09-03_004050_Леонид.jpg")
    check("имя файла помнится — иначе повтору нечего показать в ленте",
          state.seen(memory, "AgAD555")["file"] == "2026-09-03_004050_Леонид.jpg")
    check("старая память без имени файла не роняет ничего",
          state.seen(memory, "AgAD123").get("file") == "")

    for number in range(600):
        state.remember(memory, f"file{number}", number)
    check("список разобранных не растёт бесконечно",
          len(memory["seen"]) == state.SEEN_LIMIT)
    check("выкидывается старое, а не новое",
          state.seen(memory, "file599") is not None)

    state.STATE_PATH.write_text('{"seen": ["старый", "формат"]}', encoding="utf-8")
    check("список отпечатков от прежней версии не роняет бота",
          state.load()["seen"] == {})

    first = state.load()
    first["queue"].append({"merchant": "проверка"})
    check("заготовка не общая на всех", state.load()["queue"] == [])

print()
print("правка .env")

образец = (
    "# Токен бота из @BotFather\n"
    "BOT_TOKEN=\n"
    "\n"
    "# Адрес веб-приложения\n"
    "SHEET_URL=старый\n"
)

новый = config.patch_env_text(образец, {"BOT_TOKEN": "123:abc"})
check("пустое значение заполнилось", "BOT_TOKEN=123:abc" in новый)
check("комментарии на месте", "# Токен бота из @BotFather" in новый)
check("чужая строка не тронута", "SHEET_URL=старый" in новый)

новый = config.patch_env_text(образец, {"SHEET_LINK": "https://docs.google.com/x"})
check("нового ключа не было — дописался",
      новый.rstrip().endswith("SHEET_LINK=https://docs.google.com/x"))

# Закомментированный пример не должен принимать значение: иначе мастер
# впишет адрес в пример, а настоящая строка останется пустой.
новый = config.patch_env_text("# SHEET_URL=пример\nSHEET_URL=\n",
                              {"SHEET_URL": "https://script.google.com/x/exec"})
check("пример под решёткой не тронут", "# SHEET_URL=пример" in новый)
check("настоящая строка заполнилась",
      "\nSHEET_URL=https://script.google.com/x/exec" in новый)

print()
print("лента")

feed.forget()
first = feed.add({"kind": "слово", "text": "раз"})
second = feed.add({"kind": "слово", "text": "два"})
check("номера растут", first["id"] == 1 and second["id"] == 2)
check("время проставляется", first["at"] > 0)

fresh, last = feed.since(0)
check("с нуля отдаётся всё", len(fresh) == 2 and last == 2)

fresh, last = feed.since(1)
check("после первого — только второе",
      len(fresh) == 1 and fresh[0]["text"] == "два")

fresh, last = feed.since(2)
check("после последнего — пусто, номер прежний", fresh == [] and last == 2)

fresh, last = feed.since(99)
check("номер из прошлой жизни бота — отдаём журнал целиком", len(fresh) == 2)

fresh, last = feed.since(2, life="чужая-жизнь")
check("чужая метка life — тоже журнал целиком, даже если after не больше",
      len(fresh) == 2 and last == 2)

fresh, last = feed.since(2, life=feed.LIFE)
check("своя метка life — работает как раньше, по одному after",
      fresh == [] and last == 2)

feed.forget()
for number in range(feed.LIMIT + 50):
    feed.add({"kind": "слово", "text": str(number)})
fresh, last = feed.since(0)
check("лента не растёт бесконечно", len(fresh) == feed.LIMIT)
check("выкидывается старое, а не новое", fresh[-1]["text"] == str(feed.LIMIT + 49))

feed.forget()

print()
print("published() — ответ отправки из браузера")

feed.forget()
foreign = feed.add({"kind": "слово", "text": "мимо страницы"})
mine = feed.add({"kind": "мой", "text": "моё"})
result = web.published([mine])
check("курсор всегда 0 — /api/say не знает, что страница уже видела",
      result["last"] == 0)
check("события отдаются как есть, свои не путаются с чужими",
      result["events"] == [mine])
check("метка жизни едет вместе с ответом", result["life"] == feed.LIFE)
check("пустой список событий не роняет функцию",
      web.published([])["last"] == 0)

feed.forget()

print()
print("проверки без модели")
today = date(2026, 8, 23)
categories = ["Продукты", "Топливо", "Прочее"]
clean = {
    "intent": "расход", "date": "2026-08-20", "amount": 1004.7,
    "amount_source": "строка ИТОГ",
    "currency": "RUB", "merchant": "Пятёрочка", "category": "Продукты",
    "payment": "карта", "confidence": "высокая", "doubts": "",
    "reply": "Пятёрочка, 1004,70 ₽, продукты",
}

verdict = checks.review(clean, categories, today)
check("чистый чек проходит как «готово»",
      verdict["status"] == "готово" and not verdict["reasons"])

verdict = checks.review(dict(clean, date="2026-09-20"), categories, today)
check("дата в будущем ловится при высокой уверенности",
      verdict["status"] == "проверить")

verdict = checks.review(dict(clean, date="2025-01-01"), categories, today)
check("дата старше года ловится", verdict["status"] == "проверить")

# Граница: сегодня 23 августа 2026-го, ровно год назад — 23 августа 2025-го.
# Это не выдуманный край: так выглядит сегодняшний чек, у которого агент
# промахнулся годом. Codex так и промахнулся на мятом чеке.
verdict = checks.review(dict(clean, date="2025-08-23"), categories, today)
check("ровно год назад — тоже ловится", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, date="2025-08-24"), categories, today)
check("день после годовой границы проходит", verdict["status"] == "готово")

verdict = checks.review(dict(clean, date=""), categories, today)
check("пустая дата ловится", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, amount=None), categories, today)
check("пустая сумма ловится", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, amount=0), categories, today)
check("нулевая сумма ловится", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, amount=True), categories, today)
check("«да» вместо суммы ловится", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, amount=100000), categories, today)
check("ровно сто тысяч проходят", verdict["status"] == "готово")

verdict = checks.review(dict(clean, amount=100000.01), categories, today)
check("сумма больше ста тысяч ловится", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, amount_source="не нашёл"), categories, today)
check("сумма есть, а «не нашёл» — ловится даже при высокой уверенности",
      verdict["status"] == "проверить")

verdict = checks.review(dict(clean, amount_source="сложены позиции"), categories, today)
check("сумма есть, а «сложены позиции» — тоже ловится",
      verdict["status"] == "проверить")

verdict = checks.review(dict(clean, amount_source="строка ИТОГ"), categories, today)
check("строка ИТОГ — источник в порядке, статус остаётся «готово»",
      verdict["status"] == "готово")

verdict = checks.review(dict(clean, amount_source="строка К ОПЛАТЕ"), categories, today)
check("строка К ОПЛАТЕ — источник тоже в порядке, статус остаётся «готово»",
      verdict["status"] == "готово")

# Пятое значение завели потому, что четыре первых — все про чек, и на
# «такси 450 наличными» модель брала любое подходящее: Codex отвечал
# «не нашёл», Claude — «сложены позиции». Оба подозрительны, и каждая
# трата текстом уезжала со статусом «проверить».
verdict = checks.review(dict(clean, amount_source="сказано в сообщении"),
                        categories, today)
check("сумма из сообщения текстом — не повод подозревать",
      verdict["status"] == "готово")

verdict = checks.review(dict(clean, amount=None, amount_source="не нашёл"),
                         categories, today)
check("пустая сумма с «не нашёл» — это просто честный null, ловится как раньше",
      verdict["status"] == "проверить"
      and "сумма не прочиталась" in verdict["reasons"])

verdict = checks.review(dict(clean, confidence="низкая"), categories, today)
check("низкая уверенность доходит до человека",
      "агент не уверен в прочитанном" in verdict["warnings"])
check("но статуса не меняет: ресторанный чек, где не читается только вывеска, "
      "остаётся годной строкой", verdict["status"] == "готово")

verdict = checks.review(dict(clean, category="Еда"), categories, today)
check("статья не из справочника заменяется на «Прочее»",
      verdict["category"] == "Прочее")
check("но статуса не меняет", verdict["status"] == "готово")
check("и человеку про это говорится",
      any("Еда" in warning for warning in verdict["warnings"]))

# «заплатил 12000» — сумма есть, назначения нет. До 2 сентября такая строка
# уезжала в таблицу как «готово», а «проверить» получалась только тогда, когда
# агент сам признавался в неуверенности. То есть статус висел на confidence —
# на поле, которому эта таблица не верит нигде больше.
verdict = checks.review(dict(clean, merchant=""), categories, today)
check("пустой продавец ловится", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, merchant="   "), categories, today)
check("пробелы вместо продавца — то же самое", verdict["status"] == "проверить")

verdict = checks.review(dict(clean, payment="неизвестно"), categories, today)
check("а неизвестный способ оплаты статуса не меняет: «кофе 300» "
      "не обязано говорить, чем платили", verdict["status"] == "готово")

verdict = checks.review(dict(clean, doubts="время не видно"), categories, today)
check("сомнения агента доходят до человека",
      verdict["warnings"] == ["время не видно"])
check("но сами по себе статуса не меняют", verdict["status"] == "готово")

print()
print("sheet.categories() — молчащая таблица не выдаётся за пустой лист")

# Порт 1 на localhost: слушать там некому и не станет, отказ приходит сразу,
# без ожидания TIMEOUT и без обращения к настоящей сети. Так же выглядела бы
# для requests любая недоступная таблица.
unreachable = "http://127.0.0.1:1/"

blank = {"categories": [], "categories_at": 0}
found, source = sheet.categories(blank, unreachable, "секрет")
check("пустой запас и недостижимый адрес — источник «молчит», а не «нет»",
      found == [] and source == "молчит")

stocked = {"categories": ["Продукты", "Топливо"], "categories_at": 0}
found, source = sheet.categories(stocked, unreachable, "секрет")
check("запас на месте — недостижимый адрес по-прежнему отдаёт «запас»",
      found == ["Продукты", "Топливо"] and source == "запас")

print()
print("копия мозга агента")

# Боевой путь читает prompt.md. Дословная копия лежит ещё и в
# .claude/agents/expense-reader.md — чтобы звать агента руками при отладке.
# Два файла с одним текстом разъезжаются молча: правишь один, второй остаётся
# прежним, и замечаешь это через месяц, когда отладочный агент отвечает не так,
# как боевой. Пусть расхождение падает в тот же день.
root = Path(__file__).resolve().parent.parent
prompt_text = (root / "prompt.md").read_text(encoding="utf-8")
copy_path = root / ".claude" / "agents" / "expense-reader.md"

check("копия промпта на месте", copy_path.exists())
if copy_path.exists():
    copy_text = copy_path.read_text(encoding="utf-8")
    # Шапка между --- есть только у копии: она говорит Claude Code, как зовут
    # агента и что ему дать. К телу промпта она отношения не имеет.
    if copy_text.startswith("---\n"):
        copy_text = copy_text.split("\n---\n", 1)[-1]
    check("тело expense-reader.md слово в слово совпадает с prompt.md",
          copy_text.strip("\n") == prompt_text.strip("\n"))

print()
print("память последней записи")
with tempfile.TemporaryDirectory() as folder:
    state.STATE_PATH = Path(folder) / "state.json"
    memory = state.load()

    check("в заготовке есть место под последнюю запись", memory["last"] == {})

    check("у браузера адрес один на всех",
          state.address("браузер", "Лена") == state.address("браузер", "Пётр"))
    check("у каждого в телеграме свой адрес",
          state.address("телеграм", "@maria") != state.address("телеграм", "@ivan"))
    check("браузер и телеграм не сходятся в один адрес",
          state.address("браузер", "@maria") != state.address("телеграм", "@maria"))

    web_spot = state.address("браузер", "Лена")
    tg = state.address("телеграм", "@maria")

    check("пустая память ничего не отдаёт", state.last(memory, web_spot) is None)
    check("и самой свежей записи в ней тоже нет",
          state.newest(memory) == (None, None))

    state.remember_last(memory, web_spot, {"row": 47, "fields": {"amount": 450},
                                           "channel": "браузер", "author": "Лена"})
    check("записанное помнится", state.last(memory, web_spot)["row"] == 47)
    check("время проставляется само", state.last(memory, web_spot)["at"] > 0)
    check("по чужому адресу своей строки нет", state.last(memory, tg) is None)

    state.remember_last(memory, tg, {"row": 48, "fields": {"amount": 900},
                                     "channel": "телеграм", "author": "@maria"})
    check("самая свежая — та, что записана последней",
          state.newest(memory) == (tg, state.last(memory, tg)))
    check("своя строка на месте и после чужой записи",
          state.last(memory, web_spot)["row"] == 47)

    state.remember_last(memory, web_spot, {"row": 49, "fields": {"amount": 120},
                                           "channel": "браузер", "author": "Лена"})
    check("помним последнюю, а не все", state.last(memory, web_spot)["row"] == 49)

    state.save(memory)
    check("память переживает перезапуск", state.load()["last"][web_spot]["row"] == 49)


print()
print("сравнение записей")
was = {"date": "2026-09-01", "amount": 450.0, "currency": "RUB",
       "merchant": "Пятёрочка", "category": "Продукты", "payment": "карта",
       "source": "текст", "who": "Лена", "status": "готово", "file": ""}

check("одинаковые записи — пустой дифф", intake.diff(was, dict(was)) == {})
check("изменилась сумма — в диффе только сумма",
      intake.diff(was, dict(was, amount=480.0)) == {"amount": 480.0})
check("450 и 450.0 — одна и та же сумма",
      intake.diff(was, dict(was, amount=450)) == {})
check("пустая клетка и None — одно и то же",
      intake.diff(was, dict(was, file=None)) == {})
check("стереть продавца — тоже правка",
      intake.diff(was, dict(was, merchant="")) == {"merchant": ""})
check("дифф ничего не исключает: подмену источника он бы тоже заметил",
      intake.diff(was, dict(was, source="фото чека")) == {"source": "фото чека"})

check("в задании на правку есть прошлая запись",
      "Пятёрочка" in intake.rework(was, "не 450, а 480"))
check("и слова человека", "не 450, а 480" in intake.rework(was, "не 450, а 480"))
check("а происхождение строки агенту не показывается",
      "Лена" not in intake.rework(was, "не 450, а 480"))

now = dict(was, amount=480.0, category="Кафе и рестораны")
check("одно поле — «Поправил сумму: 450 → 480»",
      intake.retell(["amount"], was, now) == "Поправил сумму: 450 → 480")
check("два поля — оба в одной фразе",
      intake.retell(["amount", "category"], was, now) ==
      "Поправил сумму: 450 → 480, статью: Продукты → Кафе и рестораны")
check("копейки не теряются",
      intake.retell(["amount"], was, dict(was, amount=480.5)) ==
      "Поправил сумму: 450 → 480.50")
check("пустое значение читается как «пусто»",
      intake.retell(["merchant"], was, dict(was, merchant="")) ==
      "Поправил продавца: Пятёрочка → пусто")
check("незнакомое поле из ответа моста фразу не роняет",
      "выдумка" in intake.retell(["выдумка"], was, now))


print()
if failed:
    print(f"провалено {len(failed)}: " + ", ".join(failed))
    sys.exit(1)
print(f"проверок пройдено: {passed}")
