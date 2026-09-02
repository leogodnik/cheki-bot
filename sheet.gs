const SECRET = '__СЕКРЕТ__'; // ← сюда программа установки подставляет секрет; формат замены — в sheet-setup.md

/**
 * Мост между ботом и Google-таблицей.
 *
 * Скрипт привязан к самой таблице и опубликован веб-приложением. Умеет ровно
 * три вещи: дописать строку расхода, поправить уже записанную (то и другое —
 * doPost) и отдать справочник статей (doGet).
 * Google Cloud, сервисные аккаунты и файлы с ключами не нужны — мост существует
 * именно затем, чтобы их не заводить.
 *
 * Секрет живёт в первой строке файла. Придумывает его не человек, а программа
 * установки: она заменяет заглушку на своё значение обычной заменой текста и
 * показывает ученику уже готовый код. Тот же секрет она кладёт в .env, в
 * SHEET_SECRET, — совпадать они должны посимвольно.
 *
 * Никакой запрос без верного секрета ничего в таблице не меняет: проверка
 * стоит раньше, чем скрипт вообще смотрит на листы.
 *
 * Ошибки не роняют скрипт. Упавшее веб-приложение отвечает страницей HTML,
 * и бот на другом конце видит мусор вместо ответа. Поэтому любой отказ —
 * это такой же JSON, как и удача, только с ok: false и внятной причиной.
 */

/**
 * Порядок колонок на листе «Расходы» — тот же, что у заголовков в первой
 * строке. Записан здесь один раз: и запись новой строки, и правка одной клетки
 * считают номер колонки по этому списку. Разъедься эти два порядка — правка
 * молча писала бы сумму в чужую колонку.
 *
 * Одиннадцатой колонки в списке нет: «записано» приходит не от бота, её ставит
 * сам скрипт.
 */
const COLUMNS = ['date', 'amount', 'currency', 'merchant', 'category',
                 'payment', 'source', 'who', 'status', 'file'];
const STAMP_COLUMN = COLUMNS.length + 1; // «записано», одиннадцатая

/**
 * Принимает строку расхода и дописывает её на лист «Расходы».
 *
 * Ждёт JSON в теле POST: secret и десять полей строки. Одиннадцатую колонку,
 * «записано», ставит сам — это время записи, а не время покупки.
 *
 * Поле op выбирает, что делать. Без него — запись строки: так мост отвечал до
 * появления правки, так же отвечает и сейчас, поэтому старые запросы менять не
 * пришлось. С «правка» за дело берётся updateRow.
 *
 * Отвечает {ok: true, row: номер строки} — по этому номеру строку потом можно
 * найти глазами в таблице.
 */
function doPost(e) {
  try {
    const body = e && e.postData && e.postData.contents;
    if (!body) {
      return reply({ok: false, error: 'пустое тело запроса: строка расхода передаётся как JSON в теле POST'});
    }

    let d;
    try {
      d = JSON.parse(body);
    } catch (error) {
      return reply({ok: false, error: 'тело запроса не разбирается как JSON'});
    }
    if (!d || typeof d !== 'object') {
      return reply({ok: false, error: 'в теле запроса ожидался объект JSON с полями строки'});
    }

    // Проверка секрета — до всякого обращения к листам. Чужой запрос уходит
    // ни с чем и ничего не меняет.
    if (d.secret !== SECRET) {
      return reply({ok: false, error: 'нет доступа'});
    }

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Расходы');
    if (!sheet) {
      return reply({ok: false, error: 'в таблице нет листа «Расходы» — проверьте, не переименован ли он'});
    }

    // Обе операции живут на одном адресе: у веб-приложения Apps Script есть
    // только doGet и doPost, третьего входа не бывает. Неизвестное op — это
    // отказ, а не запись: иначе опечатка в слове «правка» тихо дописала бы
    // строку вместо того, чтобы поправить существующую.
    if (d.op === 'правка') {
      return updateRow(sheet, d);
    }
    if (has(d, 'op') && d.op !== null && d.op !== '' && d.op !== 'расход') {
      return reply({ok: false, error: 'неизвестная операция «' + text(d.op) + '»: мост знает «расход» и «правку»'});
    }

    // Значения раскладываются по колонкам в порядке COLUMNS, последней идёт
    // «записано». Пустое значение записывается пустой клеткой: appendRow не
    // принимает undefined, а «сумма не прочиталась» — обычное дело, не поломка.
    const row = COLUMNS.map(function (name) {
      const value = d[name];
      return value === undefined || value === null ? '' : value;
    });
    row.push(new Date());

    sheet.appendRow(row);
    return reply({ok: true, row: sheet.getLastRow()});
  } catch (error) {
    return reply({ok: false, error: 'таблица не смогла записать строку: ' + error.message});
  }
}

/**
 * Правит уже записанную строку: меняет только те клетки, что пришли в запросе.
 *
 * Ждёт номер строки (row), ожидаемых продавца и сумму (was_merchant,
 * was_amount) и те поля из десяти, которые изменились. Поля, которого в запросе
 * нет, правка не касается: «не 450, а 480» приходит одной суммой и меняет одну
 * клетку, а остальные девять остаются как были.
 *
 * Сверка перед записью — не перестраховка. Человек мог вставить или удалить
 * строки в таблице руками, и запомненный ботом номер начнёт указывать не туда.
 * Не совпали продавец и сумма — мост не пишет ничего и говорит, что нашёл на
 * этом месте: молча испорченная чужая строка хуже честного отказа.
 *
 * Отвечает {ok: true, row: номер, changed: [поля]} — по списку видно, что
 * именно поменялось в таблице.
 */
function updateRow(sheet, d) {
  const number = Number(d.row);
  if (!(number >= 2) || number !== Math.floor(number)) {
    return reply({ok: false, error: 'в правке нет номера строки или он не похож на номер: расходы идут со второй строки, первая — заголовки'});
  }

  // Без ожидаемых продавца и суммы сверять не с чем, и такой запрос отклоняется
  // целиком. Пропустить его «раз проверять нечего» — значит писать вслепую
  // ровно тогда, когда бот забыл сказать, что он рассчитывал там увидеть.
  if (!has(d, 'was_merchant') || !has(d, 'was_amount')) {
    return reply({ok: false, error: 'в правке нет ожидаемых продавца и суммы: без них мост в строку не пишет'});
  }

  const changed = COLUMNS.filter(function (name) { return has(d, name); });
  if (changed.length === 0) {
    return reply({ok: false, error: 'в правке не пришло ни одного поля строки: менять нечего'});
  }

  if (number > sheet.getLastRow()) {
    return reply({ok: false, error: 'строки ' + number + ' на листе «Расходы» больше нет — поправьте в таблице руками'});
  }

  const current = sheet.getRange(number, 1, 1, COLUMNS.length).getValues()[0];
  const merchant = current[COLUMNS.indexOf('merchant')];
  const amount = current[COLUMNS.indexOf('amount')];
  if (!sameText(merchant, d.was_merchant) || !sameAmount(amount, d.was_amount)) {
    return reply({ok: false, error: 'строка ' + number + ' изменилась: ожидались «' + text(d.was_merchant) +
      '» и ' + text(d.was_amount) + ', а в таблице «' + text(merchant) + '» и ' + text(amount) +
      ' — поправьте в таблице руками'});
  }

  changed.forEach(function (name) {
    const value = d[name];
    sheet.getRange(number, COLUMNS.indexOf(name) + 1)
      .setValue(value === undefined || value === null ? '' : value);
  });

  // «Записано» — время последней записи, а не рождения строки: после правки там
  // стоит время правки. Иначе колонка говорила бы про то, чего в строке уже нет.
  sheet.getRange(number, STAMP_COLUMN).setValue(new Date());

  return reply({ok: true, row: number, changed: changed});
}

/**
 * Отдаёт справочник статей с листа «Статьи»: колонка A, первая строка —
 * заголовок, пустые строки пропускаются.
 *
 * Секрет приходит параметром в адресе: ...?secret=...
 *
 * Ноль статей — это отказ, а не пустой успех. Бот, получив ok: false,
 * откажется разбирать чеки и скажет об этом человеку. Если бы он получил
 * пустой список как удачу, агент начал бы выдумывать статьи, и в отчёте
 * завелись бы «Продукты», «Продукты питания» и «Еда» вместо одной строки.
 */
function doGet(e) {
  try {
    const params = (e && e.parameter) || {};
    if (params.secret !== SECRET) {
      return reply({ok: false, error: 'нет доступа'});
    }

    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Статьи');
    if (!sheet) {
      return reply({ok: false, error: 'в таблице нет листа «Статьи» — проверьте, не переименован ли он'});
    }

    // Считаем от последней заполненной строки, а не от всей колонки: лист,
    // на котором строк меньше двух, тоже должен отвечать, а не падать.
    const last = sheet.getLastRow();
    const values = last < 2 ? [] : sheet.getRange(2, 1, last - 1, 1).getValues();
    const categories = values
      .map(function (row) { return String(row[0]).trim(); })
      .filter(function (value) { return value.length > 0; });

    if (categories.length === 0) {
      return reply({ok: false, error: 'на листе «Статьи» ни одной статьи: первая строка — заголовок, статьи идут со второй'});
    }

    return reply({ok: true, categories: categories});
  } catch (error) {
    return reply({ok: false, error: 'таблица не смогла отдать справочник: ' + error.message});
  }
}

/** Один ответ на все случаи: JSON и ничего кроме. */
function reply(o) {
  return ContentService.createTextOutput(JSON.stringify(o))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Пришло ли поле в запросе. Пришедшее пустым — пришло: «стереть продавца» тоже правка. */
function has(o, name) {
  return Object.prototype.hasOwnProperty.call(o, name);
}

/** Значение строкой, без краевых пробелов: и для сверки, и для текста отказа. */
function text(value) {
  return value === undefined || value === null ? '' : String(value).trim();
}

/**
 * Продавец сходится, если совпал без учёта регистра и краевых пробелов.
 * Строже нельзя: человек, поправивший в таблице «пятёрочка» на «Пятёрочка»,
 * строку не сдвинул — а отказ на такой правке выглядел бы поломкой.
 */
function sameText(cell, expected) {
  return text(cell).toLowerCase() === text(expected).toLowerCase();
}

/**
 * Сумма сходится, если совпала как число, а не как текст: в клетке лежит 450,
 * бот прислал «450.00» — это одна и та же сумма. Пустая клетка сходится только
 * с пустой: «сумма не прочиталась» — законное состояние строки, и правка такой
 * строки должна работать.
 *
 * Допуск в полкопейки — оттого что дробные числа хранятся приблизительно.
 */
function sameAmount(cell, expected) {
  const a = text(cell).replace(',', '.');
  const b = text(expected).replace(',', '.');
  if (a === '' || b === '') {
    return a === b;
  }
  const x = Number(a);
  const y = Number(b);
  if (isNaN(x) || isNaN(y)) {
    return a === b;
  }
  return Math.abs(x - y) < 0.005;
}

