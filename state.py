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
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state.json"

EMPTY = {
    "offset": 0,
    "seen": {},
    "categories": [],
    "categories_at": 0,
    "queue": [],
    "refused": [],
}

# Разобранные файлы не должны копиться бесконечно: они нужны, чтобы поймать
# чек, присланный дважды подряд, а не чтобы помнить всё за год.
SEEN_LIMIT = 500

# Пишут в файл два потока — телеграмный и поток разбора. Без замка они
# затрут запись друг друга на середине.
_LOCK = threading.Lock()


def load():
    """Память бота. Файла нет или он испорчен — начинаем с чистой заготовки."""
    state = json.loads(json.dumps(EMPTY))
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        state.update(data)
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return json.loads(json.dumps(EMPTY))
    if not isinstance(state["seen"], dict):
        # Файл от прежней версии бота: там был список отпечатков без номеров
        # строк. Разбирать его незачем — потеря невелика, а формат чистый.
        state["seen"] = {}
    return state


def save(state):
    """Пишем через временный файл: Ctrl+C посреди записи не оставит огрызок,
    из которого бот потом не поднимется."""
    with _LOCK:
        tmp = STATE_PATH.with_name("state.json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(STATE_PATH)


def seen(state, mark):
    """Этот файл уже разбирали? Отдаёт запомненное — номер строки и время —
    или None. Отпечаток у телеграма file_unique_id, у браузера хеш файла."""
    return state["seen"].get(mark)


def remember(state, mark, row):
    """Запомнить разобранный файл. row может быть None: строка ушла в очередь
    и номера у неё пока нет — но разбирать этот чек второй раз всё равно не надо."""
    state["seen"][mark] = {"row": row, "at": time.time()}
    extra = len(state["seen"]) - SEEN_LIMIT
    if extra > 0:
        for old in list(state["seen"])[:extra]:
            del state["seen"][old]
