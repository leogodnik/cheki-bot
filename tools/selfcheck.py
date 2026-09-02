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
import feed
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
check("низкая уверенность ловится", verdict["status"] == "проверить")

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
if failed:
    print(f"провалено {len(failed)}: " + ", ".join(failed))
    sys.exit(1)
print(f"проверок пройдено: {passed}")
