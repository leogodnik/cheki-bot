/* Рабочее место: клиент.

   Никаких библиотек и сборщиков: один файл, обычный JS. Разметка приезжает
   пустым скелетом, всё содержимое — из /api/events. Первый экран сервер не
   рисует намеренно: иначе каждое сообщение собиралось бы в двух местах, и эти
   два места разъехались бы через месяц. */

(function () {
  var app = document.getElementById("app");
  var panes = document.querySelectorAll(".pane");
  var navs = document.querySelectorAll(".nv[data-pane]");

  /* Раздел сайдбара подменяет ленту, а не открывается окном поверх — так же
     устроено приложение Claude, с которого списан вид. */
  function show(name) {
    panes.forEach(function (pane) { pane.hidden = pane.id !== "p-" + name; });
    var lit = (name === "empty") ? "feed" : name;
    navs.forEach(function (nav) {
      nav.setAttribute("aria-current", String(nav.dataset.pane === lit));
    });
    app.classList.remove("menu-open");
  }

  document.querySelectorAll("[data-pane]").forEach(function (node) {
    node.addEventListener("click", function () { show(node.dataset.pane); });
  });

  var burger = document.getElementById("burger");
  burger.addEventListener("click", function () {
    var open = app.classList.toggle("menu-open");
    burger.setAttribute("aria-expanded", String(open));
  });

  /* Пока лента пуста, показываем приглашение, а не пустое поле. */
  show("empty");
})();
