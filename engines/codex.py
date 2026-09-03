"""Codex CLI по подписке ChatGPT — второй движок за тем же швом.

Промпт, схема и все проверки общие с Claude Code. Своё здесь только то, чем
две программы отличаются, и почти всё из этого добыто прогонами 2 сентября,
а не документацией.

1. `--output-schema` принимает ПУТЬ к файлу. У Claude Code флаг `--json-schema`
   ровно наоборот — берёт текст схемы и на путь отвечает «is not valid JSON».
   Две противоположные конвенции у двух движков; перепутать их легко.
2. Промпт ставится ДО `-i`. Флаг `--image` variadic и съедает позиционный
   аргумент, если стоит перед ним: codex молча уходит читать stdin и падает
   с «No prompt provided via stdin».
3. `stdin=DEVNULL` обязателен. На открытой трубе — а из-под Flask она именно
   открытая — `codex exec` ждёт EOF и висит без конца: в разведке так зависли
   два прогона по семь и десять минут. Это не таймаут, это вечная тишина.
4. Схема делает настоящую работу, и проверять её всё равно нужно. Контрольный
   прогон без `--output-schema` вернул правдоподобный JSON — но с
   `payment_method` вместо `payment` и без `amount_source` и `currency`.
   Тот же класс поломки, что находка 3 у Claude, и даже поле совпало.
   Поэтому форму ответа сверяет шов в agent.py, а не флаг.
5. Фотографии разбираем на terra. На мятом чеке luna дважды из двух прочитала
   20.08.2026 как 20.08.2025 — промах на год назад с высокой уверенностью;
   terra и sol прочитали верно. Текст luna читает нормально.
6. Баг openai/codex#15451 (схема молча отваливается при активных инструментах
   и MCP) на codex-cli 0.152.1 не воспроизвёлся: прогон с поднятым MCP-сервером
   вернул все поля. Прогон был один — это «не воспроизвёлся», а не «исправлен»,
   и `--ignore-user-config` ниже стоит в том числе поэтому.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from engines import EngineError, resolve

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = BASE_DIR / "prompt.md"
SCHEMA_PATH = BASE_DIR / "schema.json"

MODELS = {"фото": "gpt-5.6-terra", "текст": "gpt-5.6-luna"}

# Имя команды в терминале. Отсюда его берёт agent.versions(), чтобы спросить
# версию, — а не из строки, вписанной в третьем месте.
COMMAND = "codex"
EFFORT = "low"
TIMEOUT = 180


def run(kind, task, payload):
    """Зовёт codex и возвращает разобранный ответ словарём.

    payload — путь к фотографии; для текста он не нужен. У Claude Code путь
    уезжает строкой внутри задания, и модель открывает файл сама; Codex берёт
    картинку отдельным флагом. Это и есть «способ передать картинку», которым
    движки различаются по спеке.

    Строку «Файл: …» задание при этом сохраняет — она собрана для Claude Code.
    Codex её не трогает: картинку он уже получил, и во всех прогонах шёл прямо
    к ответу, не пытаясь открыть файл сам. Вырезать её строковой хирургией
    дороже, чем оставить."""
    # Промпт у Codex некуда положить отдельно: ни `--append-system-prompt`,
    # ни его подобия здесь нет. Кладём в начало задания.
    prompt = PROMPT_PATH.read_text(encoding="utf-8") + "\n\n---\n\n" + task

    with tempfile.TemporaryDirectory() as folder:
        answer_path = Path(folder) / "answer.json"
        program = resolve(COMMAND)
        if not program:
            raise EngineError(
                "не нашёл codex — проверьте, что Codex CLI установлен "
                "(npm install -g @openai/codex) и виден в PATH"
            )
        command = [
            program, "exec",
            # Проект у ученика может лежать не под гитом — без этого codex
            # откажется работать.
            "--skip-git-repo-check",
            # Не оставлять после каждого чека сессию в ~/.codex.
            "--ephemeral",
            # Чужой config.toml не подсунет нам ни свою модель, ни свой
            # reasoning effort, ни свои MCP-серверы. У владельца в конфиге
            # стоит ultra — на разборе чека это лишние минуты и токены.
            "--ignore-user-config",
            # Разобрать чек — не повод писать на диск. Рабочим корнем даём
            # пустую временную папку: в проекте модели делать нечего.
            "-s", "read-only",
            "-C", folder,
            "-c", f'model_reasoning_effort="{EFFORT}"',
            "-m", MODELS[kind],
            "--output-schema", str(SCHEMA_PATH),
            "-o", str(answer_path),
            prompt,
        ]
        if kind == "фото":
            command += ["-i", str(payload)]

        try:
            done = subprocess.run(
                command, capture_output=True, text=True, timeout=TIMEOUT,
                stdin=subprocess.DEVNULL, cwd=folder,
            )
        except subprocess.TimeoutExpired:
            raise EngineError(f"движок молчал {TIMEOUT} секунд")
        except OSError as error:
            # Чаще всего это FileNotFoundError: codex не установлен или не
            # виден в PATH. Без этого человек получит «Смотрю чек…» и тишину.
            raise EngineError(
                "не нашёл codex — проверьте, что Codex CLI установлен "
                "(npm install -g @openai/codex) и вы вошли по подписке "
                f"ChatGPT (codex login status). Подробности: {error}"
            )

        if done.returncode != 0:
            raise EngineError(
                f"codex вышел с кодом {done.returncode}: "
                f"{done.stderr.strip()[:300]}"
            )

        raw = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""

    if not raw.strip():
        raise EngineError("codex не написал последнее сообщение — ответа нет")

    try:
        answer = json.loads(raw)
    except json.JSONDecodeError:
        # Схема отвалилась: вместо записи пришёл текст. Полный ответ — в
        # терминал, иначе поломку не с чем сличить, а она тихая.
        print("ответ движка не разобрался как JSON, вот он целиком:")
        print(raw[:2000])
        raise EngineError("ответ движка не разобрался как JSON: " + raw[:300])

    if not isinstance(answer, dict):
        raise EngineError(f"движок вернул {type(answer).__name__}, а не запись")
    return answer
