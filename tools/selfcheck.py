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
import state

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

feed.forget()
for number in range(feed.LIMIT + 50):
    feed.add({"kind": "слово", "text": str(number)})
fresh, last = feed.since(0)
check("лента не растёт бесконечно", len(fresh) == feed.LIMIT)
check("выкидывается старое, а не новое", fresh[-1]["text"] == str(feed.LIMIT + 49))

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

verdict = checks.review(dict(clean, doubts="время не видно"), categories, today)
check("сомнения агента доходят до человека",
      verdict["warnings"] == ["время не видно"])
check("но сами по себе статуса не меняют", verdict["status"] == "готово")

print()
if failed:
    print(f"провалено {len(failed)}: " + ", ".join(failed))
    sys.exit(1)
print(f"проверок пройдено: {passed}")
