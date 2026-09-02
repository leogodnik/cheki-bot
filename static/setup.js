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
