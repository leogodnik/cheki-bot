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
    state.remember(memory, "AgAD123")
    check("файл запоминается", state.seen(memory, "AgAD123"))
    check("чужой файл не считается разобранным", not state.seen(memory, "AgAD999"))

    for number in range(600):
        state.remember(memory, f"file{number}")
    check("список разобранных не растёт бесконечно",
          len(memory["seen"]) == state.SEEN_LIMIT)

    first = state.load()
    first["queue"].append({"merchant": "проверка"})
    check("заготовка не общая на всех", state.load()["queue"] == [])

print()
print("проверки без модели")
today = date(2026, 8, 23)
categories = ["Продукты", "Топливо", "Прочее"]
clean = {
    "is_expense": True, "date": "2026-08-20", "amount": 1004.7,
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
print(f"{passed} проверок, все прошли")
