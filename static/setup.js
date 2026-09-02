/* Мастер установки: клиент.

   Никаких библиотек и сборщиков, как и в рабочем месте: один файл, обычный
   JS. Своей ленты и опроса событий у мастера нет — есть переходы по экранам
   и короткие вопросы серверу.

   Файл отдельный от app.js намеренно: мастер и рабочее место никогда не
   открыты одновременно, «/» отдаёт либо одно, либо другое. Слить их значило
   бы возить на каждый экран половину чужого файла. */

(function () {
  var steps = document.querySelectorAll(".step");

  function go(id) {
    steps.forEach(function (s) { s.hidden = s.id !== id; });
    window.scrollTo(0, 0);
  }

  document.querySelectorAll("[data-go]").forEach(function (b) {
    b.addEventListener("click", function () { go(b.dataset.go); });
  });

  /* Разговор с сервером. Тот же вид, что у сайдбара: маршрут латиницей,
     тело — JSON, русские слова едут значениями, а не в адресе.

     Своей ленты у мастера нет, поэтому отказ показывается прямо на экране,
     плашкой под формой. */
  function ask(path, body) {
    return fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body || {})
    }).then(function (response) { return response.json(); })
      .catch(function () {
        return {ok: false, error: "Бот не отвечает. Посмотрите окно терминала, " +
                                  "в котором он запущен."};
      });
  }

  /* Плашка с ответом проверки. Один вид у успеха и у отказа намеренно: это
     не «ошибка», а результат проверки, и читать его надо в обоих случаях.

     textContent, а не innerHTML: в плашку едет то, что сказал сервер, — а он
     передаёт как есть отказы телеграма и Google. Вставлять чужую строку
     разметкой значит однажды получить на экране чужой тег. Заодно этим
     стирается выдуманный <b> из макета, стоявший внутри span. */
  function verdict(id, text) {
    var box = document.getElementById(id);
    box.querySelector("span").textContent = text;
    box.hidden = !text;
  }

  /* Экран можно открыть сразу по адресу: /#s-sheet */
  if (location.hash && document.querySelector(".step" + location.hash)) {
    go(location.hash.slice(1));
    setTimeout(function () { window.scrollTo(0, 0); }, 0);
  }

  /* Копирование без внешних библиотек: современный буфер обмена, а если страница
     открыта по file:// и он недоступен — старый способ через выделение. */
  document.querySelectorAll(".copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var text = btn.closest(".code").querySelector("code").innerText;
      var ok = function () { btn.textContent = "Скопировано"; setTimeout(function () { btn.textContent = "Скопировать"; }, 1600); };
      var no = function () { btn.textContent = "Выделите вручную"; setTimeout(function () { btn.textContent = "Скопировать"; }, 2200); };
      if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(ok, no); return; }
      var ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      var done = false;
      try { done = document.execCommand("copy"); } catch (e) { done = false; }
      document.body.removeChild(ta);
      done ? ok() : no();
    });
  });
})();
