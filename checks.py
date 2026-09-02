"""Проверки без модели — то, что спасает от уверенных ошибок агента.

Модель — не программа: один и тот же чек она читает по-разному и ошибается
уверенно. Поэтому ни одна проверка здесь не спрашивает у агента, уверен ли он.
«Высокая уверенность» на дате из будущего не отменяет ничего.
"""

from datetime import date, timedelta

BIG_AMOUNT = 100000
FALLBACK_CATEGORY = "Прочее"
SUSPICIOUS_SOURCES = ("не нашёл", "сложены позиции")
YEAR = timedelta(days=365)


def review(answer, categories, today):
    """Смотрит на разобранную запись и возвращает словарь:

    status   — «готово» или «проверить»
    category — статья, уже приведённая к справочнику
    reasons  — почему «проверить»; пусто, если готово
    warnings — что сказать человеку, но статус это не меняет
    """
    reasons = []
    warnings = []

    day = read_date(answer.get("date"))
    if day is None:
        reasons.append("дата не прочиталась")
    elif day > today:
        # Так ловится ошибка находки 5: агент прочитал 20 сентября,
        # когда на дворе 23 августа, и был в себе уверен.
        reasons.append(f"дата {day.isoformat()} в будущем")
    elif day <= today - YEAR:
        # Ровно год, а не «больше года». Codex на мятом чеке промахнулся
        # годом назад — 2025-08-20 вместо 2026-го — и поставил себе высокую
        # уверенность. Сегодняшний чек, прочитанный на год назад, даёт в
        # точности 365 дней, и при строгом «меньше» такая ошибка проходит.
        reasons.append(f"дата {day.isoformat()} старше года")

    amount = answer.get("amount")
    if not is_number(amount) or amount <= 0:
        reasons.append("сумма не прочиталась")
    elif amount > BIG_AMOUNT:
        # Крупная трата стоит взгляда, даже если чек читался идеально.
        reasons.append(f"крупная сумма — {amount:.2f}")

    # Число само по себе не подозрительно, и «не нашёл» само по себе тоже:
    # это как раз честный ответ вместо угадывания. Подозрительна только их
    # пара — сумма есть, а строки итога агент не видел. Порознь поля
    # невинны, вместе они и есть выдумка, и confidence её не ловит: агент
    # может быть «уверен» в числе, которое сам же и досочинил. «Сложены
    # позиции» подозрительно даже на целом чеке — если строка ИТОГ на
    # месте, складывать позиции вручную незачем.
    amount_source = answer.get("amount_source")
    if is_number(amount) and amount > 0 and amount_source in SUSPICIOUS_SOURCES:
        reasons.append(
            f"сумма {amount:.2f} есть, а итога на чеке агент не видел "
            f"(amount_source: «{amount_source}»)"
        )

    if answer.get("confidence") == "низкая":
        reasons.append("агент не уверен в прочитанном")

    doubts = (answer.get("doubts") or "").strip()
    if doubts:
        warnings.append(doubts)

    # Статья не из справочника — рабочий сигнал, а не сомнение в строке:
    # значит, в справочнике не хватает статьи, и хозяин таблицы допишет её
    # строкой на листе «Статьи». Саму строку это не портит, поэтому статус
    # не меняется — человеку просто говорится, что было и что стало.
    category = (answer.get("category") or "").strip()
    if category not in categories:
        warnings.append(
            f"статьи «{category or 'пусто'}» нет в справочнике, "
            f"записал в «{FALLBACK_CATEGORY}»"
        )
        category = FALLBACK_CATEGORY

    return {
        "status": "проверить" if reasons else "готово",
        "category": category,
        "reasons": reasons,
        "warnings": warnings,
    }


def read_date(raw):
    """ГГГГ-ММ-ДД или None. Пустая строка — тоже None: агент честно сказал,
    что даты не видит."""
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def is_number(value):
    """True у чисел, False у None и строк и — намеренно — у «да»: в питоне
    True это единица, и без этой оговорки «сумма: да» прошла бы как рубль."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)
