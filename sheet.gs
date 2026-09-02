const SECRET = 'придумайте-свою-строку';

function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  if (d.secret !== SECRET) return reply({ok: false, error: 'нет доступа'});

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Расходы');
  sheet.appendRow([
    d.date, d.amount, d.currency, d.merchant, d.category,
    d.payment, d.source, d.who, d.status, d.file, new Date()
  ]);
  return reply({ok: true, row: sheet.getLastRow()});
}

function doGet(e) {
  if (e.parameter.secret !== SECRET) return reply({ok: false, error: 'нет доступа'});

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName('Статьи');
  const categories = sheet.getRange('A2:A').getValues()
    .map(function (row) { return String(row[0]).trim(); })
    .filter(function (v) { return v.length > 0; });
  return reply({ok: true, categories: categories});
}

function reply(o) {
  return ContentService.createTextOutput(JSON.stringify(o))
    .setMimeType(ContentService.MimeType.JSON);
}
