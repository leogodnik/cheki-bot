"""Настройки бота: секреты из .env, белый список и движок из settings.json.

Файлы разделены по признаку «что случится, если удалить». Потерять .env —
настраивать заново. Потерять settings.json — заново впускать людей. Поэтому
белый список не лежит в state.json: тот файл иногда приходится удалять, когда
бот запутался, и вместе со служебным файлом человек выкинул бы себя из
собственного бота.

.env читается один раз при старте: токен и адреса на ходу не меняются.
settings.json перечитывается перед каждым сообщением — правку белого списка
руками бот подхватывает без перезапуска. В срезе 3 этот же файл будет писать
панель, и перезапуск не понадобится там тоже.
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "settings.json"

REQUIRED_ENV = ("BOT_TOKEN", "SHEET_URL", "SHEET_SECRET")

# Пустой белый список — безопасное состояние: бот не отвечает никому.
DEFAULTS = {"engine": "claude_code", "allowed": [], "knocked": [], "owner": ""}


def load_env():
    """Секреты из .env. Не хватает строки — выходим с внятным текстом."""
    load_dotenv(BASE_DIR / ".env")
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        sys.exit(
            "В .env не заполнено: " + ", ".join(missing) + ".\n"
            "Возьмите образец: cp .env.example .env"
        )
    return {
        "bot_token": os.environ["BOT_TOKEN"],
        "sheet_url": os.environ["SHEET_URL"],
        "sheet_secret": os.environ["SHEET_SECRET"],
    }


def refuse_if_api_key():
    """Ключ API в окружении уводит Claude Code с подписки на поминутную оплату,
    и человек узнаёт об этом из счёта. Лучше не запуститься."""
    if os.getenv("ANTHROPIC_API_KEY"):
        sys.exit(
            "В окружении задан ANTHROPIC_API_KEY.\n"
            "С ним Claude Code пойдёт по счётчику мимо подписки.\n"
            "Уберите строку с ANTHROPIC_API_KEY из ~/.zshrc, закройте терминал,\n"
            "откройте заново и запустите бота ещё раз."
        )


def load_settings():
    """Белый список и движок. Читается перед каждым сообщением.

    Испорченный файл — не повод падать: возвращаем пустой белый список, бот
    молчит для всех, и причина видна в терминале."""
    settings = json.loads(json.dumps(DEFAULTS))
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        settings.update(data)
    except FileNotFoundError:
        print("settings.json не найден — бот никого не впустит. "
              "cp settings.example.json settings.json")
        return json.loads(json.dumps(DEFAULTS))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        print(f"settings.json испорчен ({error}) — бот никого не впустит, "
              "пока файл не починят.")
        return json.loads(json.dumps(DEFAULTS))
    return settings


def allowed_ids(settings):
    """Числовые идентификаторы впущенных. Ник в телеграме есть не у всех,
    а номер есть всегда — и не меняется при замене бота."""
    ids = set()
    for person in settings.get("allowed", []):
        try:
            ids.add(int(person["id"]))
        except (KeyError, TypeError, ValueError):
            print(f"в settings.json строка без числового id, пропускаю: {person}")
    return ids


if __name__ == "__main__":
    env = load_env()
    refuse_if_api_key()
    settings = load_settings()
    print("токен бота:", env["bot_token"][:8] + "…")
    print("адрес таблицы:", env["sheet_url"])
    print("движок:", settings["engine"])
    print("впущено человек:", len(allowed_ids(settings)))
