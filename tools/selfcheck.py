"""Самопроверка чистых функций — тех, где тихая опечатка даёт кривые строки
в таблице.

Запуск: .venv/bin/python tools/selfcheck.py

Это не тесты проекта. Проект проверяется живьём, чеками и ботом, как написано
в спеке. Здесь только то, что можно проверить без телеграма, таблицы и модели:
служебная память и проверки без модели.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
if failed:
    print(f"провалено {len(failed)}: " + ", ".join(failed))
    sys.exit(1)
print(f"{passed} проверок, все прошли")
