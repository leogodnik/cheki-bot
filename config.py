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
import threading
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "settings.json"
ENV_PATH = BASE_DIR / ".env"

# Пишут настройки два потока: веб-запрос и — при замене бота — опрос
# телеграма. Без замка они затрут запись друг друга на середине.
_WRITE_LOCK = threading.Lock()

# Телеграм необязателен: рабочее место в браузере работает без него. Без
# таблицы бот бессмыслен — писать будет некуда.
REQUIRED_ENV = ("SHEET_URL", "SHEET_SECRET")

# Пустой белый список — безопасное состояние: бот не отвечает никому.
#
# Ник подключённого бота лежит здесь, а не в state.json, по тому же признаку,
# по какому разведены эти два файла: удаление state.json не должно ничего
# значить для человека, а «как зовут моего бота» — значит. Спрашивать getMe
# на каждом опросе ради этой строки было бы платой в сеть за то, что меняется
# раз в год.
DEFAULTS = {"engine": "claude_code", "allowed": [], "knocked": [], "owner": "",
            "bot": ""}


def load_env():
    """Секреты из .env. Не хватает строки — выходим с внятным текстом."""
    load_dotenv(BASE_DIR / ".env")
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        sys.exit(
            "В .env не заполнено: " + ", ".join(missing) + ".\n"
            "Возьмите образец: cp .env.example .env"
        )
    return read_env()


def read_env():
    """Секреты из окружения словарём. Без проверок и без чтения файла —
    файл читает load_env(), а обновляет окружение save_env()."""
    return {
        "bot_token": os.getenv("BOT_TOKEN", "").strip(),
        "sheet_url": os.getenv("SHEET_URL", "").strip(),
        "sheet_secret": os.getenv("SHEET_SECRET", "").strip(),
        "sheet_link": os.getenv("SHEET_LINK", "").strip(),
    }


def refresh_env(env):
    """Обновляет чужой словарь env на месте, из окружения.

    Именно на месте, а не новым словарём. Этот словарь держат у себя все три
    потока — веб, опрос телеграма и разбор. Присвоить переменной новый словарь
    в одном месте значит оставить два потока со старым и потом полдня искать,
    почему бот ходит в прежнюю таблицу."""
    env.update(read_env())


def patch_env_text(text, pairs):
    """Новый текст .env: значения из pairs заменены, остальное как было.

    Файл правится построчно, а не собирается заново. Причина не в
    аккуратности: .env — не только машинная память, в нём комментарии,
    объясняющие человеку, что за строка и откуда её взять. Собрать файл
    заново значит стереть их, и следующий, кто откроет .env, увидит четыре
    голых ключа без единого слова.

    Строки с решёткой пропускаются целиком: в .env.example закомментированы
    примеры вида «# SHEET_URL=…», и без этой проверки мастер вписал бы адрес
    в пример, а настоящая строка осталась бы пустой.

    Ключа в файле не нашлось — строка дописывается в конец. Значение
    вписывается без кавычек: токен, адрес и секрет из secrets.token_urlsafe
    в них не нуждаются, а лишние python-dotenv вернёт как часть значения."""
    lines = text.splitlines()
    written = set()
    for number, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        name = line.split("=", 1)[0].strip()
        if name in pairs:
            lines[number] = f"{name}={pairs[name]}"
            written.add(name)
    for name, value in pairs.items():
        if name not in written:
            lines.append(f"{name}={value}")
    return "\n".join(lines) + "\n"


def save_env(pairs):
    """Правит .env и тут же обновляет окружение процесса.

    Файла нет — берём за образец .env.example: в нём те же ключи и те же
    объяснения, ради которых файл и правится построчно. Нет и образца — пишем
    с пустого места. Пустая папка — обычный случай, а не поломка: ровно так
    ученик и начинает.

    os.environ обновляется здесь же, потому что python-dotenv читает файл один
    раз при старте и второй раз не станет. Без этой строки настройка легла бы
    на диск, а работающий бот продолжил бы жить со старым значением до
    перезапуска — ровно то, чего мы обещали не делать."""
    with _WRITE_LOCK:
        path = ENV_PATH.resolve()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            example = BASE_DIR / ".env.example"
            text = example.read_text(encoding="utf-8") if example.exists() else ""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(patch_env_text(text, pairs), encoding="utf-8")
        tmp.replace(path)
    for name, value in pairs.items():
        os.environ[name] = value


def api_key_in_env():
    """Ключ API в окружении уводит Claude Code с подписки на поминутную
    оплату, и человек узнаёт об этом из счёта.

    Раньше бот на этом просто выходил. Теперь он поднимает рабочее место и
    ничего не разбирает: объяснить на странице надёжнее, чем строкой в
    терминале, которую человек закрыл вместе с окном."""
    return bool(os.getenv("ANTHROPIC_API_KEY"))


BLOCKED_TEXT = (
    "В окружении задан ANTHROPIC_API_KEY.\n"
    "С ним Claude Code пойдёт по счётчику мимо подписки, поэтому чеки я не разбираю.\n"
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


def save_settings(settings):
    """Пишет settings.json. Единственное место записи: ни web.py, ни bot.py
    этот файл сами не открывают — иначе через месяц мест будет три, и два из
    них без замка.

    Через временный файл: Ctrl+C посреди записи не должен оставить огрызок,
    из которого бот потом никого не впустит.

    resolve() здесь обязателен, и это не украшение. В рабочих деревьях
    (git worktree) settings.json и .env — символические ссылки на общие файлы.
    replace() по ссылке заменил бы саму ссылку обычным файлом: дерево тихо
    отвязалось бы от общих настроек и дальше правило свою копию, а человек
    узнал бы об этом через день, не найдя вчерашней правки. Разрешаем ссылку
    и пишем рядом с целью."""
    with _WRITE_LOCK:
        path = SETTINGS_PATH.resolve()
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)


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
    if api_key_in_env():
        print(BLOCKED_TEXT)
    settings = load_settings()
    print("токен бота:", env["bot_token"][:8] + "…" if env["bot_token"]
          else "не задан, работаем через браузер")
    print("адрес таблицы:", env["sheet_url"])
    print("движок:", settings["engine"])
    print("впущено человек:", len(allowed_ids(settings)))
