(function () {
  "use strict";
  var EXAMPLES = [
    "隔夜开水千万别喝,会致癌",
    "微波炉热过的饭会致癌吗",
    "那个讲法医的女主剧叫什么",
    "最近有哪些演唱会还有余票"
  ];
  // 侦查阶段：后端 stage → 看板步骤
  var STEPS = [
    { key: "queued", cn: "立案", en: "FILED", note: "案件已登记，侦探出动" },
    { key: "decompose", cn: "拆解线索", en: "CLUES", note: "把问题拆成小线索" },
    { key: "search", cn: "搜查证据", en: "SEARCH", note: "调阅公开来源" },
    { key: "cross", cn: "走访民间", en: "STREET", note: "看看各平台怎么传" },
    { key: "judge", cn: "对质定案", en: "VERDICT", note: "证据对质，准备结案" }
  ];
  var PIN_SPOTS = [[13, 30], [33, 70], [52, 30], [71, 68], [88, 32]];
  var PIN_TILT = ["-4deg", "3deg", "-2deg", "4deg", "-3deg"];
  var RANKS = [
    { name: "实习侦探", xp: 0 },
    { name: "见习警探", xp: 60 },
    { name: "警探", xp: 160 },
    { name: "名侦探", xp: 320 },
    { name: "神探", xp: 600 }
  ];
  var STAMPS = {
    "真": { main: "属实", sub: "CONFIRMED", xp: 30 },
    "假": { main: "谣言", sub: "FAKE NEWS", xp: 30 },
    "说不准": { main: "存疑", sub: "UNDER DOUBT", xp: 20 },
    "没查到可靠来源": { main: "证据不足", sub: "绝不瞎编", xp: 25 }
  };
  var STORE_KEY = "detective-daily-clue";

  var form = document.getElementById("form");
  var input = document.getElementById("q");
  var go = document.getElementById("go");
  var board = document.getElementById("board");
  var boardTitle = document.getElementById("board-title");
  var stepsBox = document.getElementById("steps");
  var cork = document.getElementById("cork");
  var stringLine = document.getElementById("string");
  var reticle = document.getElementById("reticle");
  var flashEl = document.getElementById("flash");
  var typeline = document.getElementById("typeline");
  var timerEl = document.getElementById("timer");
  var progress = document.getElementById("progress");
  var errorBox = document.getElementById("error");
  var result = document.getElementById("result");
  var muteBtn = document.getElementById("mute");
  var timer = null;
  var clock = null;
  var startedAt = 0;
  var stageIndex = -1;
  var runToken = 0;
  var reduced = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function svgEl(tag, attrs) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (var k in attrs) { if (attrs.hasOwnProperty(k)) node.setAttribute(k, attrs[k]); }
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

  function hostOf(url) {
    var m = /^https?:\/\/([^\/?#]+)/i.exec(url || "");
    return m ? m[1].replace(/^www\./i, "") : "";
  }

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  // ---------- 存档（localStorage，可能被禁用） ----------
  function load() {
    var st = { cases: 0, xp: 0, streak: 0, last: "" };
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      if (raw) {
        var o = JSON.parse(raw);
        st.cases = Math.max(0, parseInt(o.cases, 10) || 0);
        st.xp = Math.max(0, parseInt(o.xp, 10) || 0);
        st.streak = Math.max(0, parseInt(o.streak, 10) || 0);
        st.last = typeof o.last === "string" ? o.last : "";
        st.muted = o.muted === true;
      }
    } catch (e) { /* 忽略 */ }
    return st;
  }
  var save = function () {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (e) { /* 忽略 */ }
  };
  var state = load();

  function dayKey(offsetDays) {
    var d = new Date(Date.now() + (offsetDays || 0) * 86400000 + 8 * 3600000); // 北京时间
    return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate());
  }

  function rankOf(xp) {
    var i = 0;
    for (var k = 0; k < RANKS.length; k++) { if (xp >= RANKS[k].xp) i = k; }
    return i;
  }

  function caseNo(n) { return "No." + ("000" + n).slice(-4); }

  function paintProfile() {
    var r = rankOf(state.xp);
    var next = RANKS[r + 1];
    document.getElementById("rank-name").textContent = RANKS[r].name;
    document.getElementById("xp-text").textContent = next ? "XP " + state.xp + " / " + next.xp : "XP " + state.xp + " · 满级";
    var base = RANKS[r].xp;
    var pct = next ? Math.round((state.xp - base) * 100 / (next.xp - base)) : 100;
    document.getElementById("xp-fill").style.width = pct + "%";
    var streak = (state.last === dayKey(0) || state.last === dayKey(-1)) ? state.streak : 0;
    document.getElementById("streak").textContent = "连续 " + streak + " 天";
    document.getElementById("edition").textContent = "EDITION No." + (state.cases + 1) + " · 5¢";
    document.getElementById("folder-tab").textContent = "案卷 " + caseNo(state.cases + 1);
  }

  // ---------- 音效（WebAudio 合成，首次用户操作后才启用） ----------
  var audio = null;
  function ensureAudio() {
    if (state.muted || audio) { if (audio && audio.state === "suspended") audio.resume(); return; }
    var Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    try { audio = new Ctx(); } catch (e) { audio = null; }
  }
  function noise(dur, freq, gain, when) {
    if (!audio || state.muted) return;
    var t = audio.currentTime + (when || 0);
    var len = Math.max(1, Math.floor(audio.sampleRate * dur));
    var buf = audio.createBuffer(1, len, audio.sampleRate);
    var data = buf.getChannelData(0);
    for (var i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
    var src = audio.createBufferSource();
    src.buffer = buf;
    var f = audio.createBiquadFilter();
    f.type = "bandpass"; f.frequency.value = freq; f.Q.value = 0.8;
    var g = audio.createGain();
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    src.connect(f); f.connect(g); g.connect(audio.destination);
    src.start(t);
  }
  function tone(f0, f1, dur, gain, type, when) {
    if (!audio || state.muted) return;
    var t = audio.currentTime + (when || 0);
    var o = audio.createOscillator();
    var g = audio.createGain();
    o.type = type || "sine";
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(f1, t + dur);
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    o.connect(g); g.connect(audio.destination);
    o.start(t); o.stop(t + dur + 0.02);
  }
  var sfx = {
    key: function () { noise(0.03, 3200 + Math.random() * 1500, 0.12); },
    shutter: function () { noise(0.05, 2500, 0.3); noise(0.08, 1200, 0.25, 0.07); },
    thud: function () { tone(150, 40, 0.35, 0.7); noise(0.18, 400, 0.5); },
    ding: function () { tone(1320, 1300, 0.5, 0.15, "triangle"); tone(1980, 1960, 0.4, 0.08, "triangle", 0.05); },
    fanfare: function () { tone(523, 520, 0.18, 0.15, "square"); tone(659, 655, 0.18, 0.15, "square", 0.15); tone(784, 780, 0.4, 0.15, "square", 0.3); }
  };
  function paintMute() {
    muteBtn.setAttribute("aria-pressed", state.muted ? "true" : "false");
    muteBtn.setAttribute("aria-label", state.muted ? "音效：关（点击开启）" : "音效：开（点击静音）");
    document.getElementById("mute-label").textContent = state.muted ? "音效 关" : "音效 开";
  }
  muteBtn.addEventListener("click", function () {
    state.muted = !state.muted;
    save(); paintMute();
    if (!state.muted) { ensureAudio(); sfx.ding(); }
  });

  // ---------- 打字机 ----------
  function typewrite(node, text, speed, token, done) {
    text = String(text || "");
    if (reduced || !text) { node.textContent = text; if (done) done(); return; }
    var i = 0;
    var seq = (node._twSeq || 0) + 1;
    node._twSeq = seq; // 新的打字任务会让旧任务停下
    node.textContent = "";
    (function step() {
      if (token !== runToken || node._twSeq !== seq) return;
      i += 1;
      node.textContent = text.slice(0, i);
      if (i % 2 === 0) sfx.key();
      if (i < text.length) setTimeout(step, speed);
      else if (done) done();
    })();
  }

  // ---------- 侦查看板 ----------
  function buildBoard() {
    stepsBox.textContent = "";
    STEPS.forEach(function (s) {
      var li = el("li", "step", s.cn);
      li.appendChild(el("span", "step-en", s.en));
      stepsBox.appendChild(li);
    });
    var notes = cork.querySelectorAll(".pin-note");
    for (var i = 0; i < notes.length; i++) cork.removeChild(notes[i]);
    stringLine.setAttribute("points", "");
    reticle.style.left = "50%"; reticle.style.top = "50%";
    stageIndex = -1;
  }

  function stepIndexOf(stage) {
    for (var i = 0; i < STEPS.length; i++) { if (STEPS[i].key === stage) return i; }
    return stage === "done" ? STEPS.length : -1;
  }

  function setStage(stage, message, token) {
    var idx = stepIndexOf(stage);
    if (idx < 0) idx = Math.max(stageIndex, 0);
    var shown = Math.min(idx, STEPS.length - 1);
    var lis = stepsBox.children;
    for (var i = 0; i < lis.length; i++) {
      lis[i].className = "step" + (i < idx ? " done" : (i === idx ? " active" : ""));
      if (i === idx) lis[i].setAttribute("aria-current", "step"); else lis[i].removeAttribute("aria-current");
    }
    var label = message || STEPS[shown].note;
    if (idx !== stageIndex) {
      for (var k = stageIndex + 1; k <= shown; k++) addPin(k, k === shown ? label : STEPS[k].note);
      stageIndex = idx;
      if (shown >= 0) { reticle.style.left = PIN_SPOTS[shown][0] + "%"; reticle.style.top = PIN_SPOTS[shown][1] + "%"; }
      flashEl.className = "flash"; void flashEl.offsetWidth; flashEl.className = "flash on";
      sfx.shutter();
      progress.textContent = "第 " + (shown + 1) + " 步，共 " + STEPS.length + " 步：" + STEPS[shown].cn + "。" + label;
      typewrite(typeline, label, 45, token);
    }
  }

  function addPin(k, text) {
    var note = el("div", "pin-note");
    note.style.left = PIN_SPOTS[k][0] + "%";
    note.style.top = PIN_SPOTS[k][1] + "%";
    note.style.setProperty("--r", PIN_TILT[k]);
    note.appendChild(el("b", null, "线索 #" + (k + 1) + " · " + STEPS[k].cn));
    note.appendChild(el("span", "pin-msg", text));
    cork.insertBefore(note, reticle);
    var pts = [];
    for (var i = 0; i <= k; i++) pts.push(PIN_SPOTS[i][0] + "," + (PIN_SPOTS[i][1] - 18));
    stringLine.setAttribute("points", pts.join(" "));
  }

  function tick() {
    var s = Math.floor((Date.now() - startedAt) / 1000);
    timerEl.textContent = pad(Math.floor(s / 60)) + ":" + pad(s % 60);
  }

  // ---------- 结果：号外头版 ----------
  function sec(cn, en) {
    var h = el("h2", "sec");
    h.appendChild(el("span", "sec-cn", cn));
    if (en) h.appendChild(document.createTextNode(en));
    return h;
  }

  var tagCount = 0;
  function evidenceTag(s, label) {
    tagCount += 1;
    var li = el("li", "tag");
    li.style.animationDelay = (reduced ? 0 : Math.min(tagCount, 12) * 0.08) + "s";
    li.appendChild(el("span", "tag-no", label || ("证物 #" + tagCount)));
    li.appendChild(link(s.url, s.title || s.url));
    var bits = [s.site || hostOf(s.url), s.date].filter(Boolean).join(" · ");
    if (bits) li.appendChild(el("span", "meta", bits));
    return li;
  }

  function sourceTags(list) {
    var ul = el("ul", "tags");
    (list || []).forEach(function (s) { ul.appendChild(evidenceTag(s)); });
    return ul;
  }

  function mugshot(no) {
    var box = el("div", "mug");
    box.setAttribute("aria-hidden", "true");
    var svg = svgEl("svg", { viewBox: "0 0 110 100" });
    svg.appendChild(svgEl("circle", { cx: "55", cy: "42", r: "22", fill: "#3a342d" }));
    svg.appendChild(svgEl("path", { d: "M14 100c4-26 20-36 41-36s37 10 41 36z", fill: "#3a342d" }));
    svg.appendChild(svgEl("rect", { x: "30", y: "78", width: "50", height: "14", fill: "#f8f3e6", stroke: "#1b1815", "stroke-width": "2" }));
    box.appendChild(svg);
    box.appendChild(el("span", "mug-no", "嫌疑 #" + no));
    return box;
  }

  function render(data, token) {
    result.textContent = "";
    tagCount = 0;
    var stampInfo = STAMPS[data.verdict] || { main: data.verdict || "待定", sub: "CASE CLOSED", xp: 10 };
    var front = el("article", "front");
    front.setAttribute("aria-label", "查证结果");

    var extra = el("div", "extra", "EXTRA! EXTRA!");
    extra.appendChild(el("small", null, "号外 · 侦探日报 · 本案已结"));
    front.appendChild(extra);
    var strip = el("div", "front-strip");
    strip.appendChild(el("span", null, "案卷 " + caseNo(state.cases)));
    strip.appendChild(el("span", null, "侦探 " + RANKS[rankOf(state.xp)].name));
    strip.appendChild(el("span", "yb-badge", "由元宝搜索提供 · 调用 " + (data.search_calls || 0) + " 次"));
    strip.appendChild(el("span", null, data.checked_at ? "截稿 " + data.checked_at : "截稿"));
    front.appendChild(strip);

    var top = el("div", "front-top");
    var left = el("div");
    left.appendChild(el("p", "kicker", "本报调查 · 查证结果"));
    var headline = el("h2", "headline");
    headline.tabIndex = -1;
    var fullClaim = data.claim || data.question || "";
    headline.appendChild(el("span", "sr-only", fullClaim));
    var typed = el("span");
    typed.setAttribute("aria-hidden", "true");
    headline.appendChild(typed);
    left.appendChild(headline);
    if (data.reasoning) left.appendChild(el("p", "reason", data.reasoning));
    top.appendChild(left);

    var zone = el("div", "stamp-zone");
    var stamp = el("div", "stamp v-" + data.verdict);
    stamp.setAttribute("role", "img");
    stamp.setAttribute("aria-label", "结论：" + data.verdict + "（" + stampInfo.main + "）");
    var sm = el("span", "stamp-main", stampInfo.main);
    sm.setAttribute("aria-hidden", "true");
    var ss = el("span", "stamp-sub", stampInfo.sub);
    ss.setAttribute("aria-hidden", "true");
    stamp.appendChild(sm); stamp.appendChild(ss);
    zone.appendChild(stamp);
    zone.appendChild(el("span", "yb-stamp", "证据来自元宝搜索 · " + (data.search_calls || 0) + " 次调用 · " + (data.evidence || []).length + " 件证物"));
    top.appendChild(zone);
    front.appendChild(top);

    var body = el("div", "front-body");

    if (data.claims && data.claims.length) {
      body.appendChild(sec("关键说法与依据", "EVIDENCE"));
      var ul = el("ul", "claim-list");
      data.claims.forEach(function (c) {
        var li = el("li", "claim-item");
        li.appendChild(el("div", "claim-text", c.text));
        if (c.sources && c.sources.length) li.appendChild(sourceTags(c.sources));
        ul.appendChild(li);
      });
      body.appendChild(ul);
    }

    if (data.candidates && data.candidates.length) {
      body.appendChild(sec("可能的答案", "SUSPECTS"));
      var cul = el("ul", "suspects");
      data.candidates.forEach(function (c, i) {
        var li = el("li", "suspect");
        li.style.animationDelay = (reduced ? 0 : i * 0.12) + "s";
        li.appendChild(mugshot(i + 1));
        li.appendChild(el("strong", "suspect-name", c.name));
        if (c.why) li.appendChild(el("span", "suspect-why", c.why));
        if (c.sources && c.sources.length) li.appendChild(sourceTags(c.sources));
        cul.appendChild(li);
      });
      body.appendChild(cul);
    }

    if (data.conflicts && data.conflicts.length) {
      body.appendChild(sec("口供矛盾", "CONFLICTING TESTIMONY"));
      data.conflicts.forEach(function (c, i) {
        var box = el("div", "conflict");
        box.appendChild(el("span", "conflict-no", "矛盾 #" + (i + 1)));
        box.appendChild(el("div", null, c.summary));
        if (c.basis) box.appendChild(el("div", "meta", "判断依据:" + c.basis));
        body.appendChild(box);
      });
    }

    if (data.verdict === "没查到可靠来源") {
      var honest = el("div", "honest");
      honest.appendChild(el("strong", "honest-title", "宁缺毋滥 · 本报拒绝瞎编"));
      honest.appendChild(el("p", null, "没有找到足够可靠的来源，所以不下判断。换个说法或补充细节再试一次。"));
      honest.appendChild(el("p", "meta", "好侦探敢说“不知道”：这次诚实结案同样计入经验。"));
      body.appendChild(honest);
    }

    if (data.sub_questions && data.sub_questions.length) {
      body.appendChild(sec("侦查笔记：证据链", "CHAIN OF EVIDENCE"));
      var ul4 = el("ol", "chain");
      data.sub_questions.forEach(function (s, i) {
        var li = el("li", "chain-step");
        li.appendChild(el("span", "chain-no", "线索 " + (i + 1)));
        li.appendChild(el("span", "chain-q", s.question));
        var qline = el("span", "chain-meta");
        qline.appendChild(el("span", "chip", "元宝搜索"));
        qline.appendChild(document.createTextNode(" 搜索词:" + s.query + " → 查到 " + s.result_count + " 条"));
        li.appendChild(qline);
        ul4.appendChild(li);
      });
      var end = el("li", "chain-step chain-end");
      end.appendChild(el("span", "chain-no", "定案"));
      end.appendChild(el("span", "chain-q", "结论：" + data.verdict + "(" + stampInfo.main + ")"));
      ul4.appendChild(end);
      body.appendChild(ul4);
    }

    if (data.evidence && data.evidence.length) {
      var d1 = el("details");
      d1.open = true;
      d1.appendChild(el("summary", null, "证物室：查到的全部来源(" + data.evidence.length + ") · 点卡片打开原文"));
      var wrap1 = el("div", "details-body");
      var pol = el("ul", "polaroids");
      data.evidence.forEach(function (e, i) {
        var li = el("li", "polaroid");
        li.style.animationDelay = (reduced ? 0 : Math.min(i, 10) * 0.06) + "s";
        var a = link(e.url, null);
        a.className = "polaroid-link";
        a.textContent = "";
        var photo = el("span", "photo");
        photo.appendChild(el("span", null, "证物 " + (e.id || ("#" + (i + 1)))));
        a.appendChild(photo);
        a.appendChild(el("span", "polaroid-title", e.title || e.url));
        var bits = [e.site || hostOf(e.url), e.date].filter(Boolean).join(" · ");
        if (bits) a.appendChild(el("span", "meta", bits));
        a.appendChild(el("span", "open-hint", "打开来源 ↗"));
        li.appendChild(a);
        pol.appendChild(li);
      });
      wrap1.appendChild(pol);
      d1.appendChild(wrap1);
      body.appendChild(d1);
    }

    if (data.folk && data.folk.length) {
      var d2 = el("details");
      d2.appendChild(el("summary", null, "走访记录：各平台上的民间讨论(只说明传到了哪里,不作为依据)"));
      var wrap2 = el("div", "details-body");
      var ul3 = el("ul", "folk-list");
      data.folk.forEach(function (f) {
        var li = el("li");
        li.appendChild(el("span", "chip", f.platform));
        li.appendChild(link(f.url, f.title));
        ul3.appendChild(li);
      });
      wrap2.appendChild(ul3);
      d2.appendChild(wrap2);
      body.appendChild(d2);
    }

    (data.notes || []).forEach(function (n) { body.appendChild(el("p", "note", "提示：" + n)); });

    var foot = el("div", "front-foot");
    var metaBox = el("div");
    metaBox.appendChild(el("div", "meta", "查询时间 " + data.checked_at + " · 元宝搜索调用 " + data.search_calls + " 次"));
    if (data.from_cache) metaBox.appendChild(el("div", "meta", "这是 " + data.cache_age_minutes + " 分钟前的查询结果。"));
    foot.appendChild(metaBox);
    var actions = el("div", "foot-actions");
    if (data.from_cache) {
      var again = el("button", "btn btn-red", "重新查询");
      again.type = "button";
      again.setAttribute("aria-label", "重新查询（不用缓存）");
      again.addEventListener("click", function () { start(data.question, true); });
      actions.appendChild(again);
    }
    var next = el("button", "btn", "下一桩案子");
    next.type = "button";
    next.addEventListener("click", function () {
      input.value = "";
      input.focus();
      if (input.scrollIntoView) input.scrollIntoView({ block: "center", behavior: reduced ? "auto" : "smooth" });
    });
    actions.appendChild(next);
    foot.appendChild(actions);
    body.appendChild(foot);
    front.appendChild(body);
    result.appendChild(front);
    headline.focus({ preventScroll: true });
    if (front.scrollIntoView) front.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });

    // 演出：标题打字 → 盖章 → 加经验
    headline.className = "headline typing";
    typewrite(typed, fullClaim, 38, token, function () {
      headline.className = "headline";
      setTimeout(function () {
        if (token !== runToken) return;
        stamp.className = "stamp slam v-" + data.verdict;
        setTimeout(function () {
          if (token !== runToken) return;
          sfx.thud();
          if (!reduced) { front.className = "front"; void front.offsetWidth; front.className = "front shake"; }
          award(data, stampInfo, front, top);
        }, reduced ? 0 : 260);
      }, reduced ? 0 : 250);
    });
  }

  function award(data, stampInfo, front, top) {
    var bonus = Math.min(10, (data.evidence || []).length);
    var gain = data.from_cache ? Math.ceil(stampInfo.xp / 2) : stampInfo.xp + bonus;
    var before = rankOf(state.xp);
    state.xp += gain;
    var today = dayKey(0);
    if (state.last !== today) {
      state.streak = state.last === dayKey(-1) ? state.streak + 1 : 1;
      state.last = today;
    }
    save();
    paintProfile();
    var pop = el("div", "xp-pop", "+" + gain + " XP");
    pop.setAttribute("aria-hidden", "true");
    top.style.position = "relative";
    top.appendChild(pop);
    var after = rankOf(state.xp);
    var msg = "结案，获得 " + gain + " 点经验。";
    if (after > before) {
      var banner = el("p", "presses");
      banner.appendChild(document.createTextNode("STOP THE PRESSES! 晋升为 "));
      banner.appendChild(el("b", null, RANKS[after].name));
      front.insertBefore(banner, front.children[1]);
      msg += "晋升为" + RANKS[after].name + "。";
      setTimeout(function () { sfx.fanfare(); }, 300);
    } else {
      setTimeout(function () { sfx.ding(); }, 200);
    }
    progress.textContent = msg;
  }

  // ---------- 流程 ----------
  function showError(message) {
    errorBox.textContent = "";
    errorBox.appendChild(el("span", "err-stamp", "悬案"));
    errorBox.appendChild(document.createTextNode(message));
    errorBox.hidden = false;
  }

  function finish(keepBoard) {
    go.disabled = false;
    if (timer) { clearTimeout(timer); timer = null; }
    if (clock) { clearInterval(clock); clock = null; }
    if (!keepBoard) board.hidden = true;
  }

  function poll(job, attempts, token) {
    fetch("/api/status/" + job).then(function (r) { return r.json(); }).then(function (s) {
      if (token !== runToken) return;
      if (s.state === "done") {
        setStage("done", "结案", token);
        finish(false);
        sfx.shutter();
        render(s.result, token);
        return;
      }
      if (s.state === "error") { finish(false); showError(s.error || "查证失败"); return; }
      setStage(s.stage, s.message || "查证中…", token);
      if (attempts > 180) { finish(false); showError("等待太久了,请稍后再试"); return; }
      timer = setTimeout(function () { poll(job, attempts + 1, token); }, 1000);
    }).catch(function () { if (token === runToken) { finish(false); showError("连接中断了,请重试"); } });
  }

  function start(question, refresh) {
    ensureAudio();
    runToken += 1;
    var token = runToken;
    if (timer) { clearTimeout(timer); timer = null; }
    if (clock) { clearInterval(clock); clock = null; }
    errorBox.hidden = true;
    result.textContent = "";
    go.disabled = true;
    state.cases += 1;
    save();
    paintProfile();
    boardTitle.textContent = "案卷 " + caseNo(state.cases) + " · 侦办中";
    buildBoard();
    board.hidden = false;
    startedAt = Date.now();
    tick();
    clock = setInterval(tick, 1000);
    if (board.scrollIntoView) board.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
    setStage("queued", "正在出发…", token);
    fetch("/api/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question, refresh: refresh === true })
    }).then(function (r) {
      return r.json().then(function (body) { return { ok: r.ok, body: body }; });
    }).then(function (res) {
      if (token !== runToken) return;
      if (!res.ok) { finish(false); showError(res.body.error || "请求失败"); return; }
      poll(res.body.job, 0, token);
    }).catch(function () { if (token === runToken) { finish(false); showError("无法连接到服务"); } });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var q = input.value.trim();
    if (!q) { showError("请先填写报案内容（要查证的话）"); input.focus(); return; }
    start(q);
  });
  input.addEventListener("keydown", function (ev) {
    if (audio && ev.key && ev.key.length === 1) sfx.key();
  });

  var holder = document.getElementById("examples");
  EXAMPLES.forEach(function (text, i) {
    var b = el("button", "clue");
    b.type = "button";
    b.setAttribute("aria-label", "填入线索：" + text);
    b.appendChild(el("span", "clue-no", "线索 #" + (i + 1)));
    b.appendChild(document.createTextNode(text));
    b.addEventListener("click", function () {
      ensureAudio();
      sfx.key();
      input.value = text;
      input.focus();
    });
    holder.appendChild(b);
  });

  try {
    document.getElementById("today").textContent = new Date().toLocaleDateString("zh-CN", {
      timeZone: "Asia/Shanghai", year: "numeric", month: "long", day: "numeric", weekday: "short"
    });
  } catch (e) {
    document.getElementById("today").textContent = dayKey(0);
  }
  paintProfile();
  paintMute();
})();
