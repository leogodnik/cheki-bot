const SECRET = '__СЕКРЕТ__'; // ← сюда программа установки подставляет секрет; формат замены — в sheet-setup.md

/**
 * Мост между ботом и Google-таблицей.
 *
 * Скрипт привязан к самой таблице и опубликован веб-приложением. Умеет ровно
 * две вещи: принять строку расхода (doPost) и отдать справочник статей (doGet).
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
 * Принимает строку расхода и дописывает её на лист «Расходы».
 *
 * Ждёт JSON в теле POST: secret и десять полей строки. Одиннадцатую колонку,
 * «записано», ставит сам — это время записи, а не время покупки.
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

    // Порядок колонок здесь и порядок заголовков на листе — одно и то же.
    // Пустое значение записывается пустой клеткой: appendRow не принимает
    // undefined, а «сумма не прочиталась» — обычное дело, не поломка.
    const row = [
      d.date, d.amount, d.currency, d.merchant, d.category,
      d.payment, d.source, d.who, d.status, d.file, new Date()
    ].map(function (value) {
      return value === undefined || value === null ? '' : value;
    });

    sheet.appendRow(row);
    return reply({ok: true, row: sheet.getLastRow()});
  } catch (error) {
    return reply({ok: false, error: 'таблица не смогла записать строку: ' + error.message});
  }
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
