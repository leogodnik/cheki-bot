"""Claude Code в headless-режиме — единственный движок первой версии.

Три вещи здесь неочевидны и добыты прогонами, а не документацией.

1. `--agent` вместе со схемой не работает: схема молча игнорируется,
   structured_output приходит пустым, а модель пишет JSON в блоке кода и
   придумывает свои имена полей. Ошибки при этом не возникает. Поэтому мозг
   агента уходит в `--append-system-prompt`, а не в агента.
2. `--json-schema` принимает текст схемы, а не путь к файлу: на путь CLI
   отвечает «--json-schema is not valid JSON».
3. Фотографии разбираем на sonnet. На мятом чеке haiku в одном прогоне из
   четырёх прочитал 20.08 как 20.09 — и поставил себе высокую уверенность.
"""

import json
import subprocess
from pathlib import Path

from engines import EngineError

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = BASE_DIR / "prompt.md"
SCHEMA_PATH = BASE_DIR / "schema.json"

MODELS = {"фото": "sonnet", "текст": "haiku"}

# Имя команды в терминале. Отсюда его берёт agent.versions(), чтобы спросить
# версию, — а не из строки, вписанной в третьем месте.
COMMAND = "claude"
TIMEOUT = 180


def run(kind, task, payload=None):
    """Зовёт claude и возвращает structured_output словарём.

    Команда собирается списком аргументов, а не строкой: в промпте есть кавычки
    и обратные кавычки, и шелл на них спотыкается — проверено.

    payload здесь не нужен и не используется: путь к фотографии уже стоит
    строкой внутри задания, и модель открывает файл сама инструментом Read.
    Аргумент есть потому, что Codex берёт картинку отдельным флагом, а шов
    зовёт оба движка одинаково."""
    command = [
        "claude",
        "-p", task,
        "--append-system-prompt", PROMPT_PATH.read_text(encoding="utf-8"),
        "--json-schema", SCHEMA_PATH.read_text(encoding="utf-8"),
        "--output-format", "json",
        "--model", MODELS[kind],
        "--allowedTools", "Read",
        "--permission-mode", "acceptEdits",
    ]
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=TIMEOUT, cwd=BASE_DIR
        )
    except subprocess.TimeoutExpired:
        raise EngineError(f"движок молчал {TIMEOUT} секунд")
    except OSError as error:
        # Чаще всего это FileNotFoundError: claude не установлен или не
        # виден в PATH. Без этого человек получит «Смотрю чек…» и тишину.
        raise EngineError(
            "не нашёл claude — проверьте, что Claude Code установлен и "
            f"виден в PATH (запустите claude --version). Подробности: {error}"
        )

    if done.returncode != 0:
        raise EngineError(
            f"claude вышел с кодом {done.returncode}: {done.stderr.strip()[:300]}"
        )

    try:
        answer = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise EngineError("ответ движка не разобрался как JSON: " + done.stdout[:300])

    if answer.get("is_error"):
        raise EngineError("движок ответил ошибкой: " + str(answer.get("result"))[:300])

    structured = answer.get("structured_output") or {}
    if not structured:
        # Схема отвалилась. Полный ответ — в терминал: без него не понять,
        # что именно сломалось, а поломка тихая и легко проходит незамеченной.
        print("пустой structured_output, полный ответ движка:")
        print(json.dumps(answer, ensure_ascii=False, indent=2))
    return structured
