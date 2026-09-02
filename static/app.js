/* Рабочее место: клиент.

   Никаких библиотек и сборщиков: один файл, обычный JS. Разметка приезжает
   пустым скелетом, всё содержимое — из /api/events. Первый экран сервер не
   рисует намеренно: иначе каждое сообщение собиралось бы в двух местах, и эти
   два места разъехались бы через месяц. */

(function () {
  var app = document.getElementById("app");
  var col = document.querySelector("#p-feed .col");
  var flow = document.querySelector("#p-feed .flow");
  var last = 0;          /* курсор ленты — с этого номера просить опросом дальше */
  var shown = {};        /* какие события уже нарисованы */
  var records = [];      /* события «запись» — из них собирается сайдбар */
  var life = null;       /* метка текущего запуска бота, из последнего ответа */
  var sheetLink = "";    /* адрес таблицы, из состояния — может не приехать вовсе */

  var today = document.getElementById("today");
  var todayNone = document.getElementById("today-none");
  var greeting = document.getElementById("greeting");
  var navTable = document.getElementById("nav-table");

  var MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
                "июля", "августа", "сентября", "октября", "ноября", "декабря"];
  var PAYMENTS = {"карта": "картой", "наличные": "наличными",
                  "перевод": "переводом", "неизвестно": ""};
  var SIGNS = {"RUB": " ₽", "USD": " $", "EUR": " €", "другая": ""};

  /* Фразы плашки разбора. Идут по порядку — примерно в том, в каком бот и
     правда работает: прочитать, найти итог, подобрать статью, записать. Дойдя
     до последней, плашка на ней и остаётся: возвращаться к «смотрю чек» после
     «записываю в таблицу» — врать про то, что происходит.

     Между рабочими фразами расставлены шуточные — «щурюсь на мелкий шрифт»,
     «спорю сам с собой о статье». Ждать полминуты веселее, а чем дольше ждёшь,
     тем дальше уходишь по списку: за пятнадцать секунд их и не увидишь.
     Шутка при этом ни разу не врёт про результат — врать про сумму, статью
     или строку в таблице нельзя даже в шутку. */
  var WORDS = {
    "фото": ["Смотрю чек", "Читаю строки", "Щурюсь на мелкий шрифт",
             "Разбираю позиции", "Ищу, где итог", "Считываю сумму",
             "Проверяю копейки", "Ищу, куда делся рубль", "Нахожу дату",
             "Смотрю, кто продавец", "Держу чек против света",
             "Соображаю, на что потратили", "Стараюсь не осуждать покупки",
             "Открываю справочник статей", "Подбираю статью",
             "Спорю сам с собой о статье", "Перепроверяю себя",
             "Считаю на пальцах", "Разбираю, что смазалось", "Собираю строку",
             "Перекладываю бумажки", "Стучусь в таблицу",
             "Уговариваю таблицу открыться", "Записываю в таблицу"],
    "текст": ["Разбираю", "Вчитываюсь", "Читаю между строк", "Ищу сумму",
              "Перечитываю ещё раз", "Смотрю валюту", "Нахожу дату",
              "Прикидываю, чем платили", "Домысливаю сокращения",
              "Соображаю, на что потратили", "Стараюсь не осуждать покупки",
              "Открываю справочник статей", "Подбираю статью",
              "Перебираю статьи по одной", "Спорю сам с собой о статье",
              "Перепроверяю себя", "Считаю на пальцах", "Морщу лоб",
              "Собираю строку", "Раскладываю по полочкам", "Стучусь в таблицу",
              "Уговариваю таблицу открыться", "Записываю в таблицу"]
  };

  /* Пятьдесят миллисекунд на букву, стирание вдвое быстрее, весь цикл фразы —
     три секунды. Длинную фразу печатать дольше, поэтому стоять она будет
     меньше; цикл при этом остаётся ровным, и плашка не частит. */
  var CYCLE = 3000, CHAR = 50, MIN_HOLD = 420;

  /* Человек мог попросить систему «уменьшить движение». Тогда фраза стоит
     целиком и ничего не бежит: такую настройку ставят не из вредности. */
  var still = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

  /* Склейка непустых кусков через « · ». Пустое поле агент возвращает честно:
     у «50 рублей сиги» продавца нет, называть его нечем и выдумывать нельзя.
     Без отсева заголовок начинался бы с разделителя: « · 50,00 ₽». */
  function join(parts) {
    return parts.filter(function (part) { return part; }).join(" · ");
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* Отправка настройки. Ответ несёт свежий снимок состояния, и сайдбар
     перерисовывается им сразу, не дожидаясь ближайшего опроса: три секунды
     между нажатием и результатом ощущаются как поломка, и человек жмёт второй
     раз. */
  function post(path, body) {
    return fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body || {})
    })
      .then(function (response) { return response.json(); })
      .then(function (answer) {
        if (answer.state) paint(answer.state);
        return answer;
      });
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

  /* «строка 5» — ссылка на эту самую строку в таблице. Google Sheets открывает
     нужную строку якорем #gid=…&range=A5; gid листа «Расходы» уже есть в адресе
     из .env, оттуда его и берём. Запасной ноль — на случай адреса без gid:
     тогда откроется первый лист, и это всё равно лучше, чем ничего.

     Адреса таблицы может не быть, и приезжает он состоянием — то есть позже
     первого события ленты. Тогда номер остаётся обычным текстом: притворяться
     ссылкой он не должен, — а href проставит linkRows(), когда адрес придёт. */
  function rowHref(row) {
    if (!sheetLink) return "";
    var gid = sheetLink.match(/[?#&]gid=(\d+)/);
    return sheetLink.split(/[?#]/)[0] + "#gid=" + (gid ? gid[1] : "0") +
      "&range=A" + row;
  }

  function rowRef(row, tail) {
    var mark = el("em");
    var link = el("a", "rw", "строка " + row);
    link.dataset.row = row;
    link.target = "_blank";
    link.rel = "noopener";
    var href = rowHref(row);
    if (href) link.href = href;
    mark.appendChild(link);
    if (tail) mark.appendChild(document.createTextNode(tail));
    return mark;
  }

  function linkRows() {
    col.querySelectorAll("a.rw").forEach(function (link) {
      var href = rowHref(link.dataset.row);
      if (href) link.href = href;
      else link.removeAttribute("href");
    });
  }

  function attach(name) {
    var att = el("span", "att");
    att.appendChild(icon("i-clip"));
    att.appendChild(document.createTextNode(name));
    return att;
  }

  /* Реплика человека — то, что он прислал. Фотография показывается самой
     фотографией: имя вроде «2026-09-02_234322_Леонид.jpg» человеку ничего не
     говорит, а свой чек он узнаёт с одного взгляда. Картинку отдаёт бот из
     папки «чеки», поэтому превью переживает перезагрузку страницы. */
  function mine(event) {
    var box = el("div", "u");
    if (event.photo) {
      box.className = "u pic";
      var img = el("img");
      img.src = "/photo/" + encodeURIComponent(event.photo);
      img.alt = "Фотография чека, которую прислали";
      /* Картинка приходит после разметки и меняет высоту пузыря — лента
         должна остаться прокрученной вниз. */
      img.addEventListener("load", function () {
        flow.scrollTop = flow.scrollHeight;
      });
      /* Файл удалили или переименовали руками — возвращаемся к имени.
         Сломанный прямоугольник вместо чека человек видеть не должен. */
      img.addEventListener("error", function () {
        box.className = "u";
        box.textContent = "";
        box.appendChild(attach(event.file || event.photo));
      });
      box.appendChild(img);
    } else if (event.file) {
      box.appendChild(attach(event.file));
    } else {
      box.textContent = event.text;
    }
    return box;
  }

  /* Плашка на те 15–50 секунд, пока бот читает. Её уберёт событие с тем же
     номером задачи.

     Молчащая плашка эти секунды выглядела мёртвой, поэтому здесь всё живёт:
     значок сканируется, фраза печатается по буквам и сменяется следующей,
     справа идёт счётчик секунд. Фразы разные для фотографии и для текста —
     разбор у них тоже разный. Событие без поля job — старая лента с прошлого
     запуска бота: тогда, как и раньше, слова про фотографию. */
  function running(event) {
    var box = el("div", "b");
    box.dataset.task = event.task;

    var hdr = el("div", "hdr");
    /* Обёртка нужна ради полоски сканера: у <svg> своих псевдоэлементов нет. */
    var ico = el("span", "ico");
    ico.appendChild(icon("mark"));
    hdr.appendChild(ico);

    var run = el("span", "run");
    var word = el("span", "wd");
    var dots = el("span", "dots");
    dots.appendChild(el("i", "", "."));
    dots.appendChild(el("i", "", "."));
    dots.appendChild(el("i", "", "."));
    var clock = el("small", "", "");
    run.appendChild(word);
    run.appendChild(el("span", "caret"));
    run.appendChild(dots);
    run.appendChild(clock);
    hdr.appendChild(run);
    box.appendChild(hdr);

    /* Печать и счётчик заводятся, когда плашка уже в ленте: до этого
       isConnected у неё false, и первый же тик принял бы её за убранную. */
    box.start = function () {
      type(box, run, word, WORDS[event.job === "текст" ? "текст" : "фото"]);
      count(box, clock, event.at);
    };
    return box;
  }

  /* Фраза печатается по буквам, стоит и стирается — и так по кругу. Пока
     печатается и стирается, мигает каретка; пока стоит целиком — оживают
     точки многоточия: вместе они бы рябили.

     Плашку убирает ответ бота, а всю ленту — перезапуск бота. Таймеры должны
     уходить вместе с ней, иначе они будут писать в выброшенную разметку до
     закрытия вкладки; узнаём об этом по isConnected, и он ловит оба случая
     сразу. */
  function type(box, run, word, words) {
    var step = 0;

    function letters(text, from, to, pace, done) {
      var n = from;
      (function next() {
        if (!box.isConnected) return;
        word.textContent = text.slice(0, n);
        if (n === to) { done(); return; }
        n += to > from ? 1 : -1;
        setTimeout(next, pace);
      })();
    }

    function cycle() {
      var text = words[step];
      run.dataset.phase = "type";
      letters(text, 0, text.length, CHAR, function () {
        run.dataset.phase = "hold";
        if (step >= words.length - 1) return;   /* последнюю фразу держим */
        /* Что не ушло на печать и стирание — стоит. Нижняя граница нужна
           самым длинным фразам: иначе они мелькали бы, не успев прочитаться. */
        setTimeout(function () {
          if (!box.isConnected) return;
          run.dataset.phase = "erase";
          letters(text, text.length, 0, CHAR / 2, function () {
            step += 1;
            cycle();
          });
        }, Math.max(MIN_HOLD, CYCLE - text.length * CHAR * 1.5));
      });
    }

    if (still) {
      run.dataset.phase = "hold";
      word.textContent = words[0];
    } else {
      cycle();
    }
  }

  /* Счётчик секунд от начала разбора. Начало берём из события, а не из
     момента отрисовки: страницу могли открыть или перезагрузить, когда чек
     уже читается. Верхней границы нет намеренно — обещать «15–50 сек» и молча
     упереться в пятьдесят хуже, чем показывать правду. */
  function count(box, clock, at) {
    var since = at ? at * 1000 : Date.now();
    var timer = setInterval(show, 250);
    show();

    function show() {
      if (!box.isConnected) { clearInterval(timer); return; }
      clock.textContent =
        Math.max(0, Math.round((Date.now() - since) / 1000)) + " сек";
    }
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
      title.appendChild(rowRef(event.row));
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
    var title = [event.merchant];
    if (event.amount !== null && event.amount !== undefined) {
      title.push(money(event.amount) + (SIGNS[event.currency] || ""));
    } else if (event.date) {
      title.push(day(event.date));
    }
    /* Не осталось ни продавца, ни суммы, ни даты — заголовок пустым не
       оставляем: «Расход» коротко и не врёт, раз запись вообще появилась. */
    box.appendChild(head(join(title) || "Расход"));
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
      var facts = join([event.category, PAYMENTS[event.payment], day(event.date),
                        event.engine]);
      sub.appendChild(document.createTextNode(facts ? facts + " — " : ""));
    }
    if (event.row) {
      sub.appendChild(rowRef(event.row,
        event.status === "проверить" ? ", на проверку" : ""));
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
    if (node.start) node.start();

    if (event.kind === "запись") records.push(event);
    flow.scrollTop = flow.scrollHeight;
  }

  /* Сайдбар. Здесь только то, что уже посчитано где-то ещё: имя из настроек,
     статьи из кэша справочника, движок и белый список из settings.json.
     Источник один — снимок состояния, приезжающий с каждым опросом ленты. */
  function paint(state) {
    greeting.textContent = state.owner
      ? "Что записываем, " + state.owner + "?"
      : "Что записываем?";

    navTable.querySelector(".r").textContent =
      state.categories ? state.categories + " статей" : "";
    sheetLink = state.sheet_link || "";
    if (sheetLink) {
      navTable.href = sheetLink;
    } else {
      /* Адреса таблицы нет — пункт не должен притворяться ссылкой. */
      navTable.removeAttribute("href");
    }
    /* Номера строк в уже нарисованной ленте ждут этого адреса. */
    linkRows();

    document.querySelectorAll(".engine-badge").forEach(function (badge) {
      badge.textContent = state.engine;
    });

    drawPeople(state);
    drawEngine(state);
  }

  /* Переключатель движка. Строится из того же ответа, что и первый шаг
     мастера: список движков и версия у каждого. Пустая версия значит «не
     установлен» — точку гасим и не даём нажать. */
  function drawEngine(state) {
    var card = document.getElementById("engine-picks");
    card.textContent = "";

    Object.keys(state.engines || {}).forEach(function (key) {
      var version = state.engines[key];
      var pick = el("label", "pick");
      var dot = document.createElement("input");
      dot.type = "radio";
      dot.name = "engine";
      dot.value = key;
      dot.checked = key === state.engine_key;
      dot.disabled = !version;
      dot.addEventListener("change", function () { post("/api/engine", {engine: key}); });
      pick.appendChild(dot);
      pick.appendChild(el("span", "nm", state.titles[key] || key));
      pick.appendChild(el("span", "tag", version || "не установлен"));
      card.appendChild(pick);
    });

    /* Выбранный движок мог исчезнуть после установки: переименовали, снесли,
       сменили PATH. Выбор человека при этом не гасим — не наше дело менять
       его молча, — но сказать, что читать чеки сейчас нечем, обязаны.
       Терракота значит «взгляни», и это ровно тот случай. */
    var gone = document.getElementById("engine-gone");
    var missing = state.engine_key && !(state.engines || {})[state.engine_key];
    gone.hidden = !missing;
    if (missing) {
      gone.querySelector("span").textContent =
        state.engine + " не отвечает в терминале. Чеки сейчас не разбираются: "
        + "поставьте его заново или выберите другой движок.";
    }
  }

  /* Одна строка списка. Ник показываем, когда он есть; когда нет — имя из
     профиля и пометку «ника нет»: заводить ник в телеграме необязательно.

     Числовой идентификатор не показывается никогда, хотя работает бот именно
     по нему. Он живёт в замыкании кнопки и уезжает обратно на сервер. */
  function person(record, label, path, hot) {
    var row = el("div", "row");
    row.appendChild(el("span", "k", record.name || "без имени"));
    row.appendChild(record.username
      ? el("span", "v nick", "@" + record.username)
      : el("span", "v noname", "ника нет"));
    var button = el("button", "bt" + (hot ? " go" : ""), label);
    button.type = "button";
    button.addEventListener("click", function () {
      /* Пока сервер думает, второе нажатие впустило бы человека дважды. */
      button.disabled = true;
      post(path, {id: record.id}).then(function (answer) {
        if (!answer.ok) button.disabled = false;
      });
    });
    row.appendChild(button);
    return row;
  }

  /* Раздел «Кто может писать» целиком. Источник один — снимок состояния;
     второго списка людей на клиенте нет и быть не должно. */
  function drawPeople(state) {
    var allowed = document.getElementById("allowed");
    var knocked = document.getElementById("knocked");
    allowed.textContent = "";
    knocked.textContent = "";

    (state.allowed || []).forEach(function (record) {
      allowed.appendChild(person(record, "Убрать", "/api/people/remove", false));
    });
    (state.knocked || []).forEach(function (record) {
      knocked.appendChild(person(record, "Впустить", "/api/people/allow", true));
    });

    document.getElementById("knocked-head").hidden = !(state.knocked || []).length;
    document.getElementById("people-none").hidden =
      (state.allowed || []).length + (state.knocked || []).length > 0;

    var count = document.querySelector("#nav-people .r");
    count.textContent = (state.knocked || []).length
      ? (state.allowed || []).length + " · стучится " + state.knocked.length
      : String((state.allowed || []).length || "");
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
      /* Запасное слово стоит на месте продавца, а не всей строки: иначе
         трата без продавца подписалась бы одним именем приславшего. */
      item.appendChild(el("span", "nm",
        join([record.merchant || "Расход", record.author])));
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

    /* У каждого запуска бота своя метка life. Сменилась — прошлая жизнь
       нарисовала не ту ленту: стираем нарисованное и last, а Math.max для
       этого ответа пропускаем — ответ отправки везёт только свои события,
       не всю ленту, и его last нельзя принимать за правду о том, что уже
       видено. Курсор наверстает опрос: у него есть свой after, и since()
       отвечает по нему точно. */
    var restarted = life !== null && answer.life !== life;
    if (restarted) {
      shown = {};
      records = [];
      col.textContent = "";
      last = 0;
    }
    life = answer.life;

    (answer.events || []).forEach(place);
    if (!restarted) {
      /* Назад номер не двигаем: ответ отправки и ответ опроса приходят в
         любом порядке, и меньший из них заставил бы спросить уже показанное. */
      last = Math.max(last, answer.last);
    }
    if (answer.state) paint(answer.state);
    drawToday();
    /* Пустое начало и лента — одно место в двух состояниях. */
    show(col.children.length ? "feed" : "empty");
  }

  /* Раз в три секунды. Вебсокетов нет намеренно: на локальном адресе опрос
     дешевле и понятнее на уроке. Сорвался запрос — молчим и пробуем снова:
     бот мог перезапускаться, и красная строка на весь экран здесь ни к чему. */
  function poll() {
    /* Своя метка life едет вместе с after: только по числу сервер не всегда
       отличит старую страницу от текущей жизни (числа могут совпасть), а по
       метке — отличит всегда. Первый опрос уходит с пустой life — тогда
       сервер решает по одному after, как раньше. */
    fetch("/api/events?after=" + last + "&life=" + encodeURIComponent(life || ""))
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
