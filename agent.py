"""Шов между ботом и движком.

bot.py зовёт parse() и получает словарь по schema.json. Какой движок стоит за
швом, бот не знает: рядом с engines/claude_code.py лёг engines/codex.py, и
bot.py не изменился ни строкой.

Движку передаётся и payload — путь к фотографии. Claude Code открывает файл
сам по строке внутри задания, Codex берёт картинку флагом `-i`; шов зовёт оба
одинаково, а как доставить картинку, решает движок.

Проверка формы ответа живёт здесь, а не в движке. Флаг схемы может отвалиться
молча у любого вендора — у Claude Code это находка 3 базовой спеки, у Codex
контрольный прогон без схемы вернул `payment_method` вместо `payment` и
потерял `amount_source` и `currency`. Одна и та же поломка у двух вендоров;
страховать от неё должен шов, а не отдельный движок.
"""

import json
import sys
from datetime import date
from pathlib import Path

from engines import EngineError, claude_code, codex

BASE_DIR = Path(__file__).resolve().parent

FIELDS = ("intent", "date", "amount", "amount_source", "currency", "merchant",
          "category", "payment", "confidence", "doubts", "reply")

INTENTS = ("расход", "правка", "не расход")

ENGINES = {"claude_code": claude_code, "codex": codex}


class AgentError(Exception):
    """Разобрать не вышло. Человеку — честный отказ, в терминал — причина."""


def parse(kind, payload, categories, today, engine="claude_code"):
    """kind — «фото» или «текст», payload — путь к файлу или текст сообщения.

    Одна повторная попытка: вызов иногда отваливается по таймауту, а второй
    заход обычно проходит. Больше двух не пробуем — каждый стоит около
    33 тысяч токенов подписки."""
    if engine not in ENGINES:
        raise AgentError(f"движок «{engine}» пока не поддержан")
    task = build_task(kind, payload, categories, today)
    for attempt in (1, 2):
        try:
            return validate(ENGINES[engine].run(kind, task, payload))
        except (EngineError, AgentError) as error:
            print(f"попытка {attempt} не удалась: {error}")
            if attempt == 2:
                raise AgentError(str(error))


def build_task(kind, payload, categories, today):
    """Задание из трёх кусков: сегодняшняя дата, вход и справочник статей.

    Дата подставляется всегда — без неё «вчера» и «в пятницу» не во что
    превратить."""
    listing = "\n".join(f"- {category}" for category in categories)
    if kind == "фото":
        what = f"Разбери чек на фотографии. Файл: {payload}"
    else:
        what = f"Разбери сообщение о расходе: {payload}"
    return (
        f"Сегодня {today.isoformat()}.\n\n"
        f"{what}\n\n"
        f"Статья расхода — строго одна строка из этого справочника:\n{listing}\n"
    )


def validate(answer):
    """Форма ответа.

    Пустой structured_output означает, что схема отвалилась. Разбирать вместо
    этого текст из блока кода нельзя: модель придумает свои имена полей
    (payment_method вместо payment, currency потеряется), и в таблицу уедет
    мусор — молча."""
    if not isinstance(answer, dict) or not answer:
        raise AgentError("пустой structured_output — схема отвалилась")
    missing = [field for field in FIELDS if field not in answer]
    if missing:
        raise AgentError("в ответе нет полей: " + ", ".join(missing))
    if answer["intent"] not in INTENTS:
        raise AgentError("intent не «расход», не «правка» и не «не расход»")
    amount = answer["amount"]
    if amount is not None and (isinstance(amount, bool)
                               or not isinstance(amount, (int, float))):
        raise AgentError("amount не число и не null")
    return answer


def seed_categories():
    """Справочник для запуска из терминала.

    Бот берёт статьи из таблицы; здесь, пока таблицы нет, читаем заготовку
    урока из categories-seed.md."""
    lines = (BASE_DIR / "categories-seed.md").read_text(encoding="utf-8").splitlines()
    return [line[2:].strip() for line in lines if line.startswith("- ")]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(
            'Как звать:\n'
            '  .venv/bin/python agent.py тестовые-чеки/01-чёткий.jpg\n'
            '  .venv/bin/python agent.py "такси 450 наличными"\n'
            '  .venv/bin/python agent.py тестовые-чеки/01-чёткий.jpg codex\n'
            'Вторым словом — движок: ' + " · ".join(ENGINES) +
            '. По умолчанию claude_code.'
        )
    argument = sys.argv[1]
    # Движок вторым аргументом — чтобы прогнать один и тот же чек двумя
    # движками подряд и положить ответы рядом.
    engine = sys.argv[2] if len(sys.argv) > 2 else "claude_code"
    path = Path(argument)
    if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
        kind, payload = "фото", str(path.resolve())
    else:
        kind, payload = "текст", argument
    categories = seed_categories()
    print(f"вход: {kind}, движок: {engine}, статей в справочнике: "
          f"{len(categories)} (из categories-seed.md)")
    print(json.dumps(parse(kind, payload, categories, date.today(), engine),
                     ensure_ascii=False, indent=2))
