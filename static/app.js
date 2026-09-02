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
  var life = null;       /* метка текущего запуска бота, из последнего ответа */

  var today = document.getElementById("today");
  var todayNone = document.getElementById("today-none");
  var greeting = document.getElementById("greeting");
  var navTable = document.getElementById("nav-table");

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

  /* Сайдбар. Здесь только то, что уже посчитано где-то ещё: имя из настроек,
     статьи из кэша справочника, движок из settings.json. Управление ими —
     срез 4, до тех пор их пункты в разметке скрыты. */
  function paint(state) {
    greeting.textContent = state.owner
      ? "Что записываем, " + state.owner + "?"
      : "Что записываем?";

    navTable.querySelector(".r").textContent =
      state.categories ? state.categories + " статей" : "";
    if (state.sheet_link) {
      navTable.href = state.sheet_link;
    } else {
      /* Адреса таблицы нет — пункт не должен притворяться ссылкой. */
      navTable.removeAttribute("href");
    }

    document.querySelectorAll(".engine-badge").forEach(function (badge) {
      badge.textContent = state.engine;
    });
  }

  /* Список того, что записано сегодня. Собирается из тех же событий, что и
     лента, — второго источника у него нет и быть не должно.

     Кружок закрашен терракотой у строк со статусом «проверить»: терракота
     значит «взгляни». */
  function drawToday() {
    var midnight = new Date();
    midnight.setHours(0, 0, 0, 0);

    var mineToday = records.filter(function (record) {
      return record.at * 1000 >= midnight.getTime();
    });

    today.textContent = "";
    mineToday.forEach(function (record) {
      var item = el("button", "li");
      item.type = "button";
      item.appendChild(el("span", "bl" + (record.status === "проверить" ? " chk" : "")));
      item.appendChild(el("span", "nm",
        record.merchant + (record.author ? " · " + record.author : "")));
      item.appendChild(el("span", "am",
        record.amount === null || record.amount === undefined ? "—" : money(record.amount)));
      item.addEventListener("click", function () {
        show("feed");
        var node = col.querySelector('[data-id="' + record.id + '"]');
        if (node) node.scrollIntoView({block: "center"});
      });
      today.appendChild(item);
    });

    today.hidden = mineToday.length === 0;
    todayNone.hidden = !today.hidden;
  }

  function receive(answer) {
    /* Бот поднял страницу, но разбирать не будет. Показываем объяснение и
       ничего больше не рисуем: лента здесь ни при чём. */
    if (answer.state && answer.state.blocked) {
      show("blocked");
      return;
    }

    /* У каждого запуска бота своя метка life; сменилась — начинаем с
       чистого листа. Первый ответ в жизни страницы метку просто запоминает. */
    if (life !== null && answer.life !== life) {
      shown = {};
      records = [];
      col.textContent = "";
      last = 0;
    }
    life = answer.life;

    (answer.events || []).forEach(place);
    /* Назад номер не двигаем: ответ отправки и ответ опроса приходят в любом
       порядке, и меньший из них заставил бы спросить уже показанное. */
    last = Math.max(last, answer.last);
    if (answer.state) paint(answer.state);
    drawToday();
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

  /* Отправка возвращается сразу, с плашкой «Смотрю чек…». Ответ приедет
     опросом. Вернувшиеся события показываем немедленно, чтобы поле не
     выглядело мёртвым три секунды. */
  function send(form) {
    fetch("/api/say", {method: "POST", body: form})
      .then(function (response) { return response.json(); })
      .then(receive)
      .catch(function () {
        place({id: 0, kind: "слово", text: "Бот не отвечает.",
               note: "Проверьте окно терминала, в котором он запущен."});
      });
  }

  function sendText(area) {
    var text = area.value.trim();
    if (!text) return;
    area.value = "";
    area.style.height = "";
    var form = new FormData();
    form.append("text", text);
    send(form);
  }

  /* Enter отправляет, Shift+Enter переносит строку — как в чате, а не как
     в форме. Поле растёт под текст: трата в три строки не должна прятаться
     под скроллом. */
  document.querySelectorAll(".box .in").forEach(function (area) {
    area.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendText(area);
      }
    });
    area.addEventListener("input", function () {
      area.style.height = "";
      area.style.height = area.scrollHeight + "px";
    });
  });

  /* Файлы уходят по одному: в очереди разбора всё равно один за другим, а
     отдельным заданием каждый получает свою плашку и свою строку в ленте. */
  function sendFiles(list) {
    Array.prototype.forEach.call(list, function (file) {
      var form = new FormData();
      form.append("file", file, file.name);
      send(form);
    });
  }

  /* Браузер шлёт dragleave и на переходе между вложенными элементами, поэтому
     считаем входы и выходы, а не гасим подсветку на первом же dragleave —
     иначе рамка мигает, пока ведёшь файл через окно. */
  var dragDepth = 0;

  function dragging(on) {
    app.classList.toggle("dragging", on);
  }

  document.addEventListener("dragenter", function (event) {
    event.preventDefault();
    dragDepth += 1;
    dragging(true);
  });

  document.addEventListener("dragover", function (event) {
    event.preventDefault();
  });

  document.addEventListener("dragleave", function (event) {
    event.preventDefault();
    dragDepth -= 1;
    if (dragDepth <= 0) { dragDepth = 0; dragging(false); }
  });

  /* Без этого браузер откроет фотографию во всю вкладку вместо того, чтобы
     отдать её боту. */
  document.addEventListener("drop", function (event) {
    event.preventDefault();
    dragDepth = 0;
    dragging(false);
    if (event.dataTransfer && event.dataTransfer.files.length) {
      sendFiles(event.dataTransfer.files);
    }
  });

  /* Перетащить можно не всегда: чек бывает в телефоне, а окно на другом
     экране. Кнопка «+» открывает обычный выбор файла — оба поля ввода
     зовут одно и то же скрытое поле. */
  var pick = document.getElementById("pick");

  document.querySelectorAll(".box .add").forEach(function (button) {
    button.addEventListener("click", function () { pick.click(); });
  });

  pick.addEventListener("change", function () {
    if (pick.files.length) sendFiles(pick.files);
    pick.value = "";   /* иначе тот же файл второй раз не выберется */
  });

  poll();
  setInterval(poll, 3000);
})();
