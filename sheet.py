"""Мост к Google-таблице через Apps Script.

Google Cloud, сервисные аккаунты и файлы с ключами не нужны: таблица сама
отвечает на два запроса — «прими строку» и «отдай справочник».

Веб-приложение Apps Script отвечает редиректом на script.googleusercontent.com.
requests переходит по нему сам, но allow_redirects отключать нельзя — иначе
вместо ответа придёт пустой 302.
"""

import sys
import time

import requests

# Три замера подряд к боевому Apps Script: 22.5 с (ReadTimeout), 19.7 с
# (успех), 20.2 с (ReadTimeout) — таблица отвечает около двадцати секунд,
# и прежние TIMEOUT = 20 не доживали до ответа две попытки из трёх. Шестьдесят
# — запас поверх измеренных двадцати, а не бесконечное ожидание.
TIMEOUT = 60
CACHE_SECONDS = 300


class SheetError(Exception):
    """Таблица не ответила или ответила не «ok»."""


class EmptyCategories(SheetError):
    """Таблица ответила, но лист «Статьи» пуст или переименован — это не то
    же самое, что таблица вовсе не ответила, и требует другого текста."""


def fetch_categories(url, secret):
    """Справочник статей прямо из таблицы, без кэша."""
    answer = ask("GET", url, params={"secret": secret})
    found = [str(item).strip() for item in answer.get("categories", [])
             if str(item).strip()]
    if not found:
        raise EmptyCategories("лист «Статьи» пуст или переименован")
    return found


def categories(state, url, secret):
    """Справочник с кэшем на пять минут и запасом из state.json.

    Возвращает (список, откуда). Кэш нужен, чтобы не дёргать таблицу на каждое
    сообщение; правка списка подхватывается сама, без перезапуска бота, —
    следующий чек после истечения кэша разберётся по-новому.

    Пустой список означает, что разбирать нельзя. Придумывать статьи агенту
    запрещено: в отчёте заведутся «Продукты», «Продукты питания» и «Еда»
    вместо одной строки.

    «Откуда» различает не только «кэш» / «запас» / «таблица», но и, когда
    список пуст, почему: «нет» — таблица ответила, а лист «Статьи» пуст или
    переименован; «молчит» — таблица вовсе не ответила (таймаут, обрыв
    соединения, не JSON). Первое — повод чинить таблицу, второе — повод
    подождать и попробовать снова; звать их одним словом «нет» посылало
    человека чинить то, что не сломано."""
    now = time.time()
    if state["categories"] and now - state["categories_at"] < CACHE_SECONDS:
        return state["categories"], "кэш"
    try:
        found = fetch_categories(url, secret)
    except EmptyCategories as error:
        if state["categories"]:
            print(f"лист «Статьи» пуст ({error}) — работаю по последнему списку")
            return state["categories"], "запас"
        print(f"лист «Статьи» пуст ({error}) — запаса тоже нет")
        return [], "нет"
    except (SheetError, requests.RequestException) as error:
        if state["categories"]:
            print(f"справочник не прочитался ({error}) — работаю по последнему списку")
            return state["categories"], "запас"
        print(f"таблица не ответила ({error}) — запаса тоже нет")
        return [], "молчит"
    state["categories"] = found
    state["categories_at"] = now
    return found, "таблица"


def append_row(url, secret, row):
    """Одна строка на лист «Расходы». Номер строки — в ответе."""
    answer = ask("POST", url, json=dict(row, secret=secret))
    return answer.get("row")


def deliver(state, url, secret, row):
    """Пишет строку и возвращает её номер. Не вышло — кладёт в очередь и
    возвращает None: разобрали, но в таблицу пока не попало."""
    try:
        return append_row(url, secret, row)
    except (SheetError, requests.RequestException) as error:
        print(f"таблица не приняла строку ({error}) — отложил в очередь")
        state["queue"].append(row)
        return None


def flush(state, url, secret):
    """Отдаёт отложенные строки по одной, в том же порядке. Сколько доехало —
    столько и вернёт; на первой неудаче останавливается."""
    delivered = 0
    while state["queue"]:
        try:
            append_row(url, secret, state["queue"][0])
        except (SheetError, requests.RequestException):
            break
        state["queue"].pop(0)
        delivered += 1
    return delivered


def ask(method, url, **kwargs):
    response = requests.request(method, url, timeout=TIMEOUT,
                                allow_redirects=True, **kwargs)
    response.raise_for_status()
    try:
        answer = response.json()
    except ValueError:
        raise SheetError("таблица ответила не JSON — проверьте, что доступ «все» "
                         "и что адрес заканчивается на /exec")
    if not answer.get("ok"):
        raise SheetError(answer.get("error", "таблица ответила не ok"))
    return answer


if __name__ == "__main__":
    import config

    env = config.load_env()
    if len(sys.argv) > 1 and sys.argv[1] == "строка":
        number = append_row(env["sheet_url"], env["sheet_secret"], {
            "date": "2026-09-01", "amount": 1, "currency": "RUB",
            "merchant": "проверка связи", "category": "Прочее",
            "payment": "неизвестно", "source": "проверка", "who": "терминал",
            "status": "проверить", "file": "",
        })
        print(f"записал строку {number} — удалите её из таблицы руками")
    else:
        found = fetch_categories(env["sheet_url"], env["sheet_secret"])
        print(f"статей в справочнике: {len(found)}")
        for item in found:
            print(" -", item)
