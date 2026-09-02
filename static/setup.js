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

  /* ═════════ Шаг 1. Движок ═════════ */

  /* Панель сама сходила в терминал и посмотрела, что установлено, — человеку
     не нужно ни знать про PATH, ни печатать команду с --version.

     Нашёлся один движок — он и выбран: выбирать не из чего, а лишний вопрос
     на первом экране отваливает половину группы. */
  function drawEngines(answer) {
    var card = document.getElementById("w-engines");
    card.textContent = "";
    var found = [];

    Object.keys(answer.engines).forEach(function (key) {
      var version = answer.engines[key];
      if (version) found.push(key);

      var pick = document.createElement("label");
      pick.className = "pick";
      var dot = document.createElement("input");
      dot.type = "radio";
      dot.name = "engine";
      dot.value = key;
      dot.disabled = !version;
      dot.checked = Boolean(version) && found.length === 1;
      pick.appendChild(dot);

      var name = document.createElement("span");
      name.className = "nm";
      name.textContent = answer.titles[key] || key;
      pick.appendChild(name);

      var tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = version || "не установлен";
      pick.appendChild(tag);

      card.appendChild(pick);
    });

    /* Не нашлось ничего — тупик, и это правильный ответ, а не поломка
       мастера: без движка бот бессмыслен, читать чек будет нечем. */
    if (!found.length) go("s-noengine");
  }

  function loadEngines() {
    fetch("/api/engines")
      .then(function (response) { return response.json(); })
      .then(drawEngines)
      .catch(function () {});
  }

  document.getElementById("w-recheck").addEventListener("click", loadEngines);
  document.getElementById("w-noengine-recheck")
    .addEventListener("click", loadEngines);

  document.getElementById("w-engine-next").addEventListener("click", function () {
    var picked = document.querySelector("#w-engines input:checked");
    if (!picked) return;
    /* Выбор запоминается тем же маршрутом, которым его меняет сайдбар.
       Второго места, где движок ложится в settings.json, нет. */
    ask("/api/engine", {engine: picked.value}).then(function () { go("s-sheet"); });
  });

  loadEngines();

  /* ═════════ Шаг 2. Таблица ═════════ */

  /* Код для таблицы. Приезжает с сервера целиком, с уже подставленным
     секретом: придумывать и запоминать человеку нечего, а кнопка
     «Скопировать» рядом уже работает — она берёт текст из этого же узла. */
  function loadScript() {
    fetch("/api/setup/script")
      .then(function (response) { return response.json(); })
      .then(function (answer) {
        document.getElementById("w-code").textContent =
          answer.ok ? answer.code : answer.error;
      })
      .catch(function () {});
  }

  document.getElementById("w-check").addEventListener("click", function () {
    var field = document.getElementById("webapp");
    verdict("w-said", "Спрашиваю таблицу…");
    ask("/api/setup/sheet", {url: field.value}).then(function (answer) {
      verdict("w-said", answer.error || answer.note);
      /* «Готово» открывается только когда справочник прочитан целиком.
         Пропустить человека дальше с пятнадцатью статьями значит отдать ему
         бота, который на первом же чеке напишет «Прочее». */
      document.getElementById("w-sheet-next").disabled = !answer.ready;
      /* Адрес таблицы мастер запомнил сам — поле освобождаем под второй. */
      if (!answer.ok) field.select();
    });
  });

  loadScript();

  /* ═════════ Готово и третий, необязательный шаг ═════════ */

  /* Строка сводки. Тот же вид, что в карточках сайдбара. */
  function line(key, value) {
    var row = document.createElement("div");
    row.className = "row";
    var left = document.createElement("span");
    left.className = "k";
    left.textContent = key;
    var right = document.createElement("span");
    right.className = "v";
    right.textContent = value;
    row.appendChild(left);
    row.appendChild(right);
    return row;
  }

  /* Сводка на экране готовности. Числа берутся у сервера, а не запоминаются
     по дороге: человек мог поправить таблицу в соседней вкладке, и сводка,
     собранная из ответов десятиминутной давности, соврала бы. */
  function drawSummary(id) {
    fetch("/api/summary")
      .then(function (response) { return response.json(); })
      .then(function (answer) {
        var state = answer.state;
        var card = document.getElementById(id);
        card.textContent = "";
        card.appendChild(line("Движок", state.engine));
        card.appendChild(line("Таблица", state.categories + " статей"));
        card.appendChild(line("Телеграм", state.telegram
          ? "@" + state.bot : "не подключён"));
        if (state.owner) card.appendChild(line("Может писать", state.owner));
      })
      .catch(function () {});
  }

  document.getElementById("w-sheet-next")
    .addEventListener("click", function () { drawSummary("w-summary"); });

  document.getElementById("w-tg-start").addEventListener("click", function () {
    go("s-token");
  });

  document.getElementById("w-token-check").addEventListener("click", function () {
    var token = document.getElementById("token").value.trim();
    verdict("w-token-said", "Спрашиваю телеграм…");
    ask("/api/telegram/check", {token: token}).then(function (answer) {
      verdict("w-token-said", answer.ok
        ? "Токен принят. Бота зовут @" + answer.username + " — это он?"
        : answer.error);
      document.getElementById("w-token-go").disabled = !answer.ok;
    });
  });

  document.getElementById("w-token-go").addEventListener("click", function () {
    var token = document.getElementById("token").value.trim();
    /* Сохраняем тем же маршрутом, которым бота меняет сайдбар. Он же
       перезапустит опрос: без работающего опроса следующий экран ждал бы
       сообщения, которого никто не читает. */
    ask("/api/telegram/save", {token: token}).then(function (answer) {
      if (!answer.ok) { verdict("w-token-said", answer.error); return; }
      document.getElementById("w-bot-name").textContent = "@" + answer.username;
      go("s-wait");
    });
  });

  /* Кого человек уже отверг на «Это вы?». Без этого списка «Нет, ждём дальше»
     возвращало бы на тот же экран через две секунды: опрос увидел бы того же
     стучавшегося и снова счёл бы его первым. */
  var notMe = {};

  document.getElementById("w-hello-no").addEventListener("click", function () {
    notMe[document.getElementById("w-hello-yes").dataset.id] = true;
  });

  /* Ждём, пока человек напишет своему боту. Вводить сюда ничего не нужно:
     числовой идентификатор приедет сам, и человек его не увидит никогда.

     Проверка на скрытый экран заменяет собой остановку таймера: экранов
     мало, опрос дешёвый, а забытый clearInterval — обычный способ получить
     переход на чужом экране. */
  setInterval(function () {
    if (document.getElementById("s-wait").hidden) return;
    fetch("/api/summary")
      .then(function (response) { return response.json(); })
      .then(function (answer) {
        var knocked = (answer.state.knocked || []).filter(function (person) {
          return !notMe[person.id];
        });
        if (!knocked.length) return;
        var first = knocked[0];
        var card = document.getElementById("w-knocker");
        card.textContent = "";
        card.appendChild(line(first.name || "без имени",
          first.username ? "@" + first.username : "ника нет"));
        verdict("w-hello-said", "Это вы, " +
          (first.username ? "@" + first.username : first.name) + "?");
        document.getElementById("w-hello-yes").dataset.id = first.id;
        go("s-hello");
      })
      .catch(function () {});
  }, 2000);

  document.getElementById("w-hello-yes").addEventListener("click", function () {
    var id = document.getElementById("w-hello-yes").dataset.id;
    ask("/api/people/allow", {id: id}).then(function () {
      drawSummary("w-summary2");
      go("s-tgdone");
    });
  });

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
