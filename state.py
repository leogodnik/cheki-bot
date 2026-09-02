"""state.json — служебная память бота.

Хранит четыре вещи: offset телеграма (чтобы после перезапуска не разбирать всё
заново), уже разобранные файлы, последний прочитанный справочник статей и
очередь строк, не доехавших до таблицы. Плюс тех, кому уже отказали, — чтобы
не отвечать чужому дважды.

Удалять можно, только когда очередь пуста: если бот отвечал «Разобрал, но
в таблицу не попало — попробую позже», в файле лежат строки расходов, которых
больше нигде нет. Белого списка здесь намеренно нет, он живёт в settings.json.
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state.json"

EMPTY = {
    "offset": 0,
    "seen": [],
    "categories": [],
    "categories_at": 0,
    "queue": [],
    "refused": [],
}

# Список разобранных файлов не должен расти бесконечно: он нужен, чтобы
# поймать чек, присланный дважды подряд, а не чтобы помнить всё за год.
SEEN_LIMIT = 500


def load():
    """Память бота. Файла нет или он испорчен — начинаем с чистой заготовки."""
    state = json.loads(json.dumps(EMPTY))
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state.update(data)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return json.loads(json.dumps(EMPTY))
    return state


def save(state):
    """Пишем через временный файл: Ctrl+C посреди записи не оставит огрызок,
    из которого бот потом не поднимется."""
    tmp = STATE_PATH.with_name("state.json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def seen(state, unique_id):
    """Этот файл уже разбирали? Ловится по file_unique_id из телеграма."""
    return unique_id in state["seen"]


def remember(state, unique_id):
    state["seen"].append(unique_id)
    del state["seen"][:-SEEN_LIMIT]
