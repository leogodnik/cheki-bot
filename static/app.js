/* Рабочее место: клиент.

   Никаких библиотек и сборщиков: один файл, обычный JS. Разметка приезжает
   пустым скелетом, всё содержимое — из /api/events. Первый экран сервер не
   рисует намеренно: иначе каждое сообщение собиралось бы в двух местах, и эти
   два места разъехались бы через месяц. */

(function () {
  var app = document.getElementById("app");
  var col = document.querySelector("#p-feed .col");
  var flow = document.querySelector("#p-feed .flow");
  var last = 0;          /* номер последнего показанного события */
  var shown = {};        /* какие события уже нарисованы */
  var records = [];      /* события «запись» — из них собирается сайдбар */

  var MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
                "июля", "августа", "сентября", "октября", "ноября", "декабря"];
  var PAYMENTS = {"карта": "картой", "наличные": "наличными",
                  "перевод": "переводом", "неизвестно": ""};
  var SIGNS = {"RUB": " ₽", "USD": " $", "EUR": " €", "другая": ""};

  /* 1004.7 → «1 004,70». Разряды отбиваем неразрывным пробелом, иначе строка
     переносится посреди числа. Дробную часть при этом не трогаем: правило
     «по три цифры» применимо только к целой. */
  function money(sum) {
    var parts = sum.toFixed(2).split(".");
    return parts[0].replace(/\B(?=(\d{3})+$)/g, " ") + "," + parts[1];
  }

  /* «2026-08-20» → «20 августа». Пустая дата — пустая строка: агент честно
     сказал, что даты не видит, и выдумывать её здесь тем более незачем. */
  function day(iso) {
    if (!iso) return "";
    var parts = String(iso).split("-");
    if (parts.length !== 3) return "";
    return Number(parts[2]) + " " + MONTHS[Number(parts[1]) - 1];
  }

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

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* Иконку рисуем ссылкой на <symbol> в шапке страницы — те же значки, что
     в эталоне. className у SVG только для чтения, поэтому setAttribute. */
  function icon(name) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", name === "mark" ? "mark" : "ic");
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#" + name);
    svg.appendChild(use);
    return svg;
  }

  /* Названия магазинов приезжают из фотографии, прочитанной моделью. Всё,
     что от неё пришло, ставим только через textContent: innerHTML на таких
     данных — дыра. */
  function head(text) {
    var hdr = el("div", "hdr");
    hdr.appendChild(icon("mark"));
    hdr.appendChild(el("b", "", text));
    return hdr;
  }

  /* Подпись только у чужого. Человек впереди способа: значимо, кто потратил,
     а не с какого устройства прислал. */
  function source(event, box) {
    if (event.author) box.appendChild(el("div", "src", event.author + " · " + event.channel));
  }

  /* Реплика человека — то, что он прислал. */
  function mine(event) {
    var box = el("div", "u");
    if (event.file) {
      var att = el("span", "att");
      att.appendChild(icon("i-clip"));
      att.appendChild(document.createTextNode(event.file));
      box.appendChild(att);
    } else {
      box.textContent = event.text;
    }
    return box;
  }

  /* «Смотрю чек…» — плашка на 15–50 секунд. Её уберёт событие с тем же
     номером задачи. */
  function running(event) {
    var box = el("div", "b");
    box.dataset.task = event.task;
    var hdr = el("div", "hdr");
    hdr.appendChild(icon("mark"));
    var run = el("span", "run", "Смотрю чек… ");
    run.appendChild(el("small", "", "15–50 сек"));
    hdr.appendChild(run);
    box.appendChild(hdr);
    return box;
  }

  /* Фраза бота: отказ или пояснение. Её сочиняет агент или сам бот — здесь
     переписывать нечего, только показать. */
  function said(event) {
    var box = el("div", "b");
    source(event, box);
    var hdr = el("div", "hdr");
    hdr.appendChild(icon("mark"));
    var title = el("b", "", event.text);
    if (event.row) {
      title.appendChild(document.createTextNode(" — "));
      title.appendChild(el("em", "", "строка " + event.row));
    }
    hdr.appendChild(title);
    box.appendChild(hdr);
    if (event.note) box.appendChild(el("div", "sub", event.note));
    return box;
  }

  /* Запись расхода. Фразу собираем здесь, из полей: сервер отдаёт числа и
     слова, а разряды, знак валюты и порядок — дело вёрстки. */
  function written(event) {
    var box = el("div", "b");
    source(event, box);
    var title = event.merchant;
    if (event.amount !== null && event.amount !== undefined) {
      title += " · " + money(event.amount) + (SIGNS[event.currency] || "");
    } else if (event.date) {
      title += " · " + day(event.date);
    }
    box.appendChild(head(title));
    box.appendChild(details(event));
    return box;
  }

  /* Вторая строка записи. У чистой — «продукты · картой · 20 августа —
     строка 47». У пойманной проверками — сама причина плашкой и «на
     проверку»: терракота значит «взгляни», и только это. */
  function details(event) {
    var sub = el("div", "sub");
    var trouble = (event.reasons || []).concat(event.warnings || []);
    if (event.status === "проверить" && trouble.length) {
      sub.appendChild(el("span", "warn", trouble[0]));
      sub.appendChild(document.createTextNode(" — "));
    } else {
      var facts = [event.category, PAYMENTS[event.payment], day(event.date)]
        .filter(function (part) { return part; });
      sub.appendChild(document.createTextNode(facts.join(" · ") + " — "));
    }
    if (event.row) {
      sub.appendChild(el("em", "", "строка " + event.row +
        (event.status === "проверить" ? ", на проверку" : "")));
    } else {
      sub.appendChild(el("em", "", "в таблицу пока не попало"));
    }
    return sub;
  }

  function place(event) {
    /* Отправка и опрос идут навстречу друг другу и возвращают одни и те же
       события: отправка — сразу, опрос — потому что успел начаться раньше.
       Без этой проверки трата нарисовалась бы дважды. Номер 0 у событий,
       которые страница придумала сама, — их не помним. */
    if (event.id > 0) {
      if (shown[event.id]) return;
      shown[event.id] = true;
    }

    /* Ответ пришёл — плашка «Смотрю чек…» своё отслужила. */
    if (event.task && event.kind !== "работа") {
      var pending = col.querySelector('[data-task="' + event.task + '"]');
      if (pending) pending.remove();
    }

    var node = event.kind === "мой" ? mine(event)
             : event.kind === "работа" ? running(event)
             : event.kind === "запись" ? written(event)
             : said(event);
    node.dataset.id = event.id;
    col.appendChild(node);

    if (event.kind === "запись") records.push(event);
    flow.scrollTop = flow.scrollHeight;
  }

  function receive(answer) {
    (answer.events || []).forEach(place);
    /* Назад номер не двигаем: ответ отправки и ответ опроса приходят в любом
       порядке, и меньший из них заставил бы спросить уже показанное. */
    last = Math.max(last, answer.last);
    /* Пустое начало и лента — одно место в двух состояниях. */
    show(col.children.length ? "feed" : "empty");
  }

  /* Раз в три секунды. Вебсокетов нет намеренно: на локальном адресе опрос
     дешевле и понятнее на уроке. Сорвался запрос — молчим и пробуем снова:
     бот мог перезапускаться, и красная строка на весь экран здесь ни к чему. */
  function poll() {
    fetch("/api/events?after=" + last)
      .then(function (response) { return response.json(); })
      .then(receive)
      .catch(function () {});
  }

  poll();
  setInterval(poll, 3000);
})();
