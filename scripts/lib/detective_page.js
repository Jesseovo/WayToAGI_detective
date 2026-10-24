(function () {
  "use strict";
  var EXAMPLES = [
    "隔夜开水千万别喝,会致癌",
    "微波炉热过的饭会致癌吗",
    "那个讲法医的女主剧叫什么",
    "最近有哪些演唱会还有余票"
  ];
  var form = document.getElementById("form");
  var input = document.getElementById("q");
  var go = document.getElementById("go");
  var progress = document.getElementById("progress");
  var errorBox = document.getElementById("error");
  var result = document.getElementById("result");
  var timer = null;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function safeHref(url) {
    return /^https?:\/\//i.test(url || "") ? url : "#";
  }

  function link(url, text) {
    var a = el("a", "source-link", text || url);
    a.href = safeHref(url);
    a.target = "_blank";
    a.rel = "noopener noreferrer nofollow";
    return a;
  }

  function section(title) {
    return el("h2", "content-section", title);
  }

  function sourceLine(s) {
    var li = el("li", "source-item");
    li.appendChild(link(s.url, s.title || s.url));
    var bits = [s.site, s.date].filter(Boolean).join(" · ");
    if (bits) li.appendChild(el("span", "meta source-meta", bits));
    return li;
  }

  function render(data) {
    result.textContent = "";
    var card = el("div", "card result-card");
    var head = el("div", "result-head");
    var summary = el("div", "result-summary");
    summary.appendChild(el("p", "result-kicker", "查证结果"));
    summary.appendChild(el("div", "claim", data.claim || data.question));
    if (data.reasoning) summary.appendChild(el("p", "reason", data.reasoning));
    head.appendChild(summary);
    var verdict = el("div", "verdict-wrap");
    verdict.appendChild(el("span", "badge v-" + data.verdict, data.verdict));
    head.appendChild(verdict);
    card.appendChild(head);
    var body = el("div", "result-body");

    if (data.claims && data.claims.length) {
      body.appendChild(section("关键说法与依据"));
      var ul = el("ul", "claim-list");
      data.claims.forEach(function (c) {
        var li = el("li", null, c.text);
        var inner = el("ul", "source-list");
        (c.sources || []).forEach(function (s) { inner.appendChild(sourceLine(s)); });
        if (inner.childNodes.length) li.appendChild(inner);
        ul.appendChild(li);
      });
      body.appendChild(ul);
    }

    if (data.candidates && data.candidates.length) {
      body.appendChild(section("可能的答案"));
      var cul = el("ul", "candidate-list");
      data.candidates.forEach(function (c) {
        var li = el("li");
        li.appendChild(el("strong", null, c.name));
        if (c.why) li.appendChild(el("span", null, " — " + c.why));
        var inner = el("ul", "source-list");
        (c.sources || []).forEach(function (s) { inner.appendChild(sourceLine(s)); });
        if (inner.childNodes.length) li.appendChild(inner);
        cul.appendChild(li);
      });
      body.appendChild(cul);
    }

    if (data.conflicts && data.conflicts.length) {
      body.appendChild(section("来源之间的分歧"));
      data.conflicts.forEach(function (c) {
        var box = el("div", "conflict");
        box.appendChild(el("div", null, c.summary));
        if (c.basis) box.appendChild(el("div", "meta", "判断依据:" + c.basis));
        body.appendChild(box);
      });
    }

    if (data.verdict === "没查到可靠来源") {
      body.appendChild(el("p", "note", "没有找到足够可靠的来源，所以不下判断。换个说法或补充细节再试一次。"));
    }

    if (data.evidence && data.evidence.length) {
      var d1 = el("details");
      d1.appendChild(el("summary", null, "查到的全部来源(" + data.evidence.length + ")"));
      var ul2 = el("ul", "source-list");
      data.evidence.forEach(function (e) {
        var li = sourceLine(e);
        li.insertBefore(el("span", "meta", e.id + " "), li.firstChild);
        ul2.appendChild(li);
      });
      d1.appendChild(ul2);
      body.appendChild(d1);
    }

    if (data.folk && data.folk.length) {
      var d2 = el("details");
      d2.appendChild(el("summary", null, "各平台上的民间讨论(只说明传到了哪里,不作为依据)"));
      var ul3 = el("ul", "source-list");
      data.folk.forEach(function (f) {
        var li = el("li");
        li.appendChild(el("span", "meta", f.platform + " · "));
        li.appendChild(link(f.url, f.title));
        ul3.appendChild(li);
      });
      d2.appendChild(ul3);
      body.appendChild(d2);
    }

    if (data.sub_questions && data.sub_questions.length) {
      var d3 = el("details");
      d3.appendChild(el("summary", null, "调查过程"));
      var ul4 = el("ul");
      data.sub_questions.forEach(function (s) {
        ul4.appendChild(el("li", null, s.question + "(搜索词:" + s.query + ",查到 " + s.result_count + " 条)"));
      });
      d3.appendChild(ul4);
      body.appendChild(d3);
    }

    (data.notes || []).forEach(function (n) { body.appendChild(el("p", "note", "提示：" + n)); });
    var foot = el("div", "result-foot");
    foot.appendChild(el("span", "meta", "查询时间 " + data.checked_at + " · 元宝搜索调用 " + data.search_calls + " 次"));
    if (data.from_cache) {
      var cacheLine = el("span", "meta", "这是 " + data.cache_age_minutes + " 分钟前的查询结果。 ");
      var again = el("button", "linkish", "重新查询");
      again.type = "button";
      again.addEventListener("click", function () { start(data.question, true); });
      cacheLine.appendChild(again);
      foot.appendChild(cacheLine);
    }
    body.appendChild(foot);
    card.appendChild(body);
    result.appendChild(card);
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.hidden = false;
  }

  function finish() {
    go.disabled = false;
    progress.textContent = "";
    if (timer) { clearTimeout(timer); timer = null; }
  }

  function poll(job, attempts) {
    fetch("/api/status/" + job).then(function (r) { return r.json(); }).then(function (s) {
      if (s.state === "done") { finish(); render(s.result); return; }
      if (s.state === "error") { finish(); showError(s.error || "查证失败"); return; }
      progress.textContent = s.message || "查证中…";
      if (attempts > 180) { finish(); showError("等待太久了,请稍后再试"); return; }
      timer = setTimeout(function () { poll(job, attempts + 1); }, 1000);
    }).catch(function () { finish(); showError("连接中断了,请重试"); });
  }

  function start(question, refresh) {
    errorBox.hidden = true;
    result.textContent = "";
    go.disabled = true;
    progress.textContent = "正在出发…";
    fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, refresh: refresh === true })
    }).then(function (r) {
      return r.json().then(function (body) { return { ok: r.ok, body: body }; });
    }).then(function (res) {
      if (!res.ok) { finish(); showError(res.body.error || "请求失败"); return; }
      poll(res.body.job, 0);
    }).catch(function () { finish(); showError("无法连接到服务"); });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var q = input.value.trim();
    if (!q) { showError("请先输入要查证的内容"); return; }
    start(q);
  });

  var holder = document.getElementById("examples");
  EXAMPLES.forEach(function (text) {
    var b = el("button", null, text);
    b.type = "button";
    b.addEventListener("click", function () { input.value = text; input.focus(); });
    holder.appendChild(b);
  });
})();
