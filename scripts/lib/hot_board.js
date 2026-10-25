(function () {
  'use strict';
  var root = document.documentElement;
  var query = document.getElementById('q');
  var filters = Array.from(document.querySelectorAll('[data-filter]'));
  var boards = Array.from(document.querySelectorAll('.board'));
  var topics = Array.from(document.querySelectorAll('.topic'));
  var topicSection = document.getElementById('topics-section');
  var topicToggle = document.getElementById('topics-toggle');
  var summary = document.getElementById('board-summary');
  var empty = document.getElementById('empty');
  var clear = document.getElementById('search-clear');
  var group = 'all';
  var expandedTopics = false;
  var limit = 6;
  var narrowScreen = window.matchMedia('(max-width: 640px)');
  var reader = document.getElementById('board-reader');
  var readerList = document.getElementById('reader-list');
  var sourceTabs = Array.from(document.querySelectorAll('.source-tab'));
  var sourceNav = document.querySelector('.source-nav');
  var sourceToggle = document.getElementById('source-toggle');
  var sourcePicker = document.getElementById('source-picker');
  var sourceCurrent = document.getElementById('source-current');
  var activeBoard = 0;

  function closePicker(restoreFocus) {
    sourcePicker.hidden = true;
    sourceToggle.setAttribute('aria-expanded', 'false');
    document.getElementById('source-toggle-label').textContent = '切换线人';
    if (restoreFocus) sourceToggle.focus({ preventScroll: true });
  }

  function platformMatches(board, value) {
    return matches(board, value) || (board.getAttribute('data-code') || '').toLowerCase() === value;
  }

  function matchedRows(board, value) {
    return Array.from(board.querySelectorAll('li')).filter(function (row) {
      return !value || platformMatches(board, value) || matches(row, value);
    });
  }

  function matches(node, value) {
    return (node.getAttribute('data-k') || '').toLowerCase().indexOf(value) !== -1;
  }

  function update() {
    var value = query.value.trim().toLowerCase();
    var matchingItems = 0;
    var visibleBoards = 0;
    var visibleTopics = 0;
    var available = [];
    var matchedCounts = [];
    var mobile = narrowScreen.matches;
    root.classList.toggle('is-searching', !!value);
    clear.hidden = !query.value;
    filters.forEach(function (button) {
      button.setAttribute('aria-pressed', String(button.getAttribute('data-filter') === group));
    });
    boards.forEach(function (board, index) {
      var inGroup = group === 'all' || board.getAttribute('data-group') === group;
      var rows = Array.from(board.querySelectorAll('li'));
      var count = 0;
      var platformMatch = platformMatches(board, value);
      var shown = 0;
      rows.forEach(function (row) {
        var match = !value || platformMatch || matches(row, value);
        if (match) count++;
        row.hidden = !match || (!mobile && shown >= limit);
        if (match) shown++;
      });
      // Keep failed sources visible until a keyword filter is applied.
      board.hidden = !inGroup || (!!value && !count);
      if (!board.hidden) {
        available.push(index);
        visibleBoards++;
        matchingItems += count;
      }
      board.classList.toggle('board-empty', !rows.length);
      matchedCounts[index] = count;
      board.style.setProperty('--preview-rows', String(Math.min(count, limit)));
      var opener = board.querySelector('.board-open');
      if (opener) {
        opener.querySelector('span').textContent = value ? '调阅 ' + count + ' 条匹配' : '调阅全部 ' + rows.length + ' 条';
        opener.setAttribute('aria-label', '调阅' + board.querySelector('h3').textContent + (value ? '的' + count + '条匹配' : '完整卷宗'));
      }
      var counter = board.querySelector('.board-count');
      if (rows.length) counter.textContent = value ? count + ' 条匹配' : rows.length + ' 条';
    });
    if (available.indexOf(activeBoard) === -1) activeBoard = available.length ? available[0] : -1;
    sourceTabs.forEach(function (tab, index) {
      tab.hidden = available.indexOf(index) === -1;
      tab.setAttribute('aria-pressed', String(index === activeBoard));
      var counter = tab.querySelector('.source-match');
      counter.hidden = !value;
      counter.textContent = matchedCounts[index] + ' 条';
    });
    boards.forEach(function (board, index) {
      if (mobile) board.hidden = index !== activeBoard;
    });
    topics.forEach(function (topic) {
      var inGroup = group === 'all' || (topic.getAttribute('data-groups') || '').split(' ').indexOf(group) !== -1;
      var match = inGroup && (!value || matches(topic, value));
      if (match) visibleTopics++;
      topic.hidden = !match || (!value && !expandedTopics && visibleTopics > (narrowScreen.matches ? 1 : 3));
    });
    if (topicSection) {
      topicSection.hidden = !visibleTopics;
      topicSection.classList.toggle('is-expanded', expandedTopics || !!value);
      topicToggle.hidden = !!value || visibleTopics <= (narrowScreen.matches ? 1 : 3);
      topicToggle.setAttribute('aria-expanded', String(expandedTopics));
      topicToggle.querySelector('span').textContent = expandedTopics ? '收起' : '查看全部 ' + visibleTopics + ' 个';
    }
    summary.textContent = value ? '搜出 ' + matchingItems + ' 条线索 · ' + visibleBoards + ' 份报告' : mobile ? visibleBoards + ' 路线人' : visibleBoards + ' 份报告 · 先看前 ' + limit + ' 条';
    sourceNav.hidden = !available.length;
    document.getElementById('source-picker-count').textContent = available.length + ' 路线人';
    sourceCurrent.textContent = '';
    if (activeBoard >= 0) {
      var selected = sourceTabs[activeBoard];
      sourceCurrent.appendChild(selected.querySelector('.platform-icon').cloneNode(true));
      var label = document.createElement('span');
      label.textContent = boards[activeBoard].querySelector('h3').textContent;
      sourceCurrent.appendChild(label);
    }
    if (!mobile || !available.length) closePicker(false);
    empty.hidden = visibleBoards > 0 || visibleTopics > 0;
  }

  filters.forEach(function (button) {
    button.addEventListener('click', function () {
      group = button.getAttribute('data-filter');
      closePicker(false);
      update();
    });
  });
  sourceTabs.forEach(function (tab, index) {
    tab.addEventListener('click', function () {
      var pinned = sourceNav.getBoundingClientRect().top <= 1;
      activeBoard = index;
      update();
      closePicker(true);
      if (narrowScreen.matches && pinned) boards[index].scrollIntoView({ block: 'start' });
    });
  });
  sourceToggle.addEventListener('click', function () {
    if (!sourcePicker.hidden) { closePicker(false); return; }
    sourcePicker.hidden = false;
    sourceToggle.setAttribute('aria-expanded', 'true');
    document.getElementById('source-toggle-label').textContent = '收起';
    if (sourcePicker.getBoundingClientRect().bottom > window.innerHeight) sourceNav.scrollIntoView({ block: 'start' });
  });
  sourceNav.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && !sourcePicker.hidden) {
      event.preventDefault();
      closePicker(true);
    }
  });
  sourceNav.addEventListener('focusout', function (event) {
    if (!sourceNav.contains(event.relatedTarget)) closePicker(false);
  });
  document.addEventListener('pointerdown', function (event) {
    if (!sourceNav.contains(event.target)) closePicker(false);
  });
  query.addEventListener('input', function () { closePicker(false); update(); });
  if (narrowScreen.addEventListener) narrowScreen.addEventListener('change', update);
  query.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { query.value = ''; update(); }
  });
  clear.addEventListener('click', function () { query.value = ''; update(); query.focus(); });
  document.getElementById('reset').addEventListener('click', function () {
    group = 'all'; query.value = ''; update(); query.focus();
  });
  boards.forEach(function (board) {
    var opener = board.querySelector('.board-open');
    if (opener) opener.addEventListener('click', function () {
      var value = query.value.trim().toLowerCase();
      var rows = matchedRows(board, value);
      readerList.textContent = '';
      rows.forEach(function (row) {
        var copy = row.cloneNode(true);
        copy.hidden = false;
        readerList.appendChild(copy);
      });
      var icon = document.getElementById('reader-icon');
      icon.textContent = '';
      icon.appendChild(board.querySelector('.platform-icon').cloneNode(true));
      document.getElementById('reader-title').textContent = board.querySelector('h3').textContent;
      document.getElementById('reader-context').textContent = value ? '搜查「' + query.value.trim() + '」 · ' + rows.length + ' 条匹配' : '本次快照共 ' + rows.length + ' 条线报 · 按来源排名排列';
      reader.showModal();
      readerList.scrollTop = 0;
      root.classList.add('reader-open');
    });
  });
  document.getElementById('reader-close').addEventListener('click', function () { reader.close(); });
  reader.addEventListener('close', function () { root.classList.remove('reader-open'); });
  reader.addEventListener('click', function (event) {
    var rect = reader.getBoundingClientRect();
    if (event.target === reader && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) reader.close();
  });
  if (topicToggle) topicToggle.addEventListener('click', function () {
    var collapsing = expandedTopics;
    expandedTopics = !expandedTopics;
    update();
    if (collapsing) topicToggle.scrollIntoView({ block: 'nearest' });
  });

  var themeButton = document.getElementById('theme-toggle');
  var systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  function dark() {
    return root.getAttribute('data-theme') === 'dark' || (!root.hasAttribute('data-theme') && systemTheme.matches);
  }
  function themeLabel() {
    themeButton.setAttribute('aria-label', dark() ? '切换至日班（浅色主题）' : '切换至夜班（深色主题）');
    themeButton.title = themeButton.getAttribute('aria-label');
    document.getElementById('theme-label').textContent = dark() ? '日班' : '夜班';
  }
  themeButton.addEventListener('click', function () {
    var theme = dark() ? 'light' : 'dark';
    root.setAttribute('data-theme', theme);
    try { localStorage.setItem('last30days-hot-theme', theme); } catch (e) { /* Offline/private browsing still works. */ }
    themeLabel();
  });
  if (systemTheme.addEventListener) systemTheme.addEventListener('change', themeLabel);

  var starNudge = document.getElementById('star-nudge');
  var starDismissKey = 'last30days-hot-star-dismissed-until';
  var starDismissed = false;
  try { starDismissed = Number(localStorage.getItem(starDismissKey)) > Date.now(); } catch (e) { /* The prompt still works without storage. */ }
  function dismissStar() {
    starDismissed = true;
    starNudge.hidden = true;
    try { localStorage.setItem(starDismissKey, String(Date.now() + 30 * 24 * 60 * 60 * 1000)); } catch (e) { /* Dismiss for this visit if storage is unavailable. */ }
  }
  function showStar() {
    if (starDismissed) return;
    // Wait for an unobstructed reading moment without taking keyboard focus.
    if (document.hidden || reader.open || !sourcePicker.hidden || document.activeElement === query) {
      window.setTimeout(showStar, 2500);
      return;
    }
    starNudge.hidden = false;
  }
  document.getElementById('star-close').addEventListener('click', dismissStar);
  document.getElementById('star-link').addEventListener('click', dismissStar);
  starNudge.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') { event.preventDefault(); dismissStar(); }
  });
  if (!starDismissed) window.setTimeout(showStar, 12000);
  // --- Case-solving game: investigated links, clue points and detective rank. ---
  var GAME_KEY = 'last30days-hot-casebook';
  var RANKS = [[0, '实习侦探'], [60, '见习侦探'], [180, '正式侦探'], [400, '资深侦探'], [800, '名侦探'], [1500, '神探']];
  var edition = (document.querySelector('.mast-rule time') || {}).textContent || '';
  var motion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var book = { edition: edition, seen: {}, points: 0 };
  try {
    var saved = JSON.parse(localStorage.getItem(GAME_KEY) || 'null');
    if (saved && typeof saved === 'object') {
      book.points = Math.max(0, Number(saved.points) || 0);
      // Investigations reset with each new edition; the career score carries over.
      if (saved.edition === edition && saved.seen && typeof saved.seen === 'object') book.seen = saved.seen;
    }
  } catch (e) { /* Corrupt or blocked storage starts a fresh casebook. */ }
  function saveBook() {
    try { localStorage.setItem(GAME_KEY, JSON.stringify(book)); } catch (e) { /* Play continues for this visit. */ }
  }
  function storyKey(anchor) { return 's:' + anchor.getAttribute('href') + '|' + (anchor.getAttribute('title') || ''); }
  function topicKey(topic) { return 'c:' + (topic.querySelector('a.t').getAttribute('title') || ''); }
  var hudPoints = document.getElementById('hud-points');
  var hudRank = document.getElementById('hud-rank');
  var hudFill = document.getElementById('hud-fill');
  var hudBar = document.getElementById('hud-bar');
  var hudCount = document.getElementById('hud-count');
  var hudNext = document.getElementById('hud-next');
  var caseStatus = document.getElementById('case-status');
  var toast = document.getElementById('clue-toast');
  var storyLinks = Array.from(document.querySelectorAll('.board .story'));
  function rankFor(points) {
    var current = RANKS[0], next = null;
    RANKS.forEach(function (r, i) { if (points >= r[0]) { current = r; next = RANKS[i + 1] || null; } });
    return { name: current[1], next: next };
  }
  function paintSeen() {
    topics.forEach(function (topic) { topic.classList.toggle('is-solved', !!book.seen[topicKey(topic)]); });
    storyLinks.forEach(function (a) { a.parentNode.classList.toggle('is-read', !!book.seen[storyKey(a)]); });
  }
  function paintHud() {
    var useCases = topics.length > 0;
    var pool = useCases ? topics.map(topicKey) : storyLinks.map(storyKey);
    var done = pool.filter(function (k) { return book.seen[k]; }).length;
    var pct = pool.length ? Math.round(done * 100 / pool.length) : 0;
    var rank = rankFor(book.points);
    hudPoints.textContent = String(book.points);
    hudRank.textContent = rank.name;
    hudFill.style.width = pct + '%';
    hudBar.setAttribute('aria-valuenow', String(pct));
    hudCount.textContent = (useCases ? '悬案 ' : '线报 ') + done + ' / ' + pool.length;
    hudNext.textContent = pool.length && pct === 100 ? '本期悬案全部告破，干得漂亮。' : rank.next ? '再得 ' + (rank.next[0] - book.points) + ' 分晋升「' + rank.next[1] + '」' : '你已是神探，继续巡查吧。';
  }
  function popToast(text, anchor) {
    toast.textContent = text;
    toast.hidden = false;
    var rect = anchor.getBoundingClientRect();
    toast.style.left = Math.max(12, Math.min(window.innerWidth - 160, rect.left + rect.width / 2 - 60)) + 'px';
    toast.style.top = Math.max(12, rect.top - 12) + 'px';
    toast.classList.remove('is-pop');
    void toast.offsetWidth;
    toast.classList.add('is-pop');
    window.clearTimeout(popToast.timer);
    popToast.timer = window.setTimeout(function () { toast.hidden = true; }, motion ? 1100 : 1800);
  }
  function award(key, points, message, anchor, slamNode) {
    if (book.seen[key]) return;
    var before = rankFor(book.points).name;
    book.seen[key] = 1;
    book.points += points;
    saveBook();
    paintSeen();
    paintHud();
    var after = rankFor(book.points).name;
    var promoted = after !== before ? '晋升「' + after + '」！' : '';
    caseStatus.textContent = message + '，线索积分 +' + points + '。' + promoted;
    popToast('+' + points + ' 线索' + (promoted ? ' · ' + after : ''), anchor);
    if (slamNode) {
      slamNode.classList.remove('just-solved');
      void slamNode.offsetWidth;
      slamNode.classList.add('just-solved');
    }
  }
  function investigate(event) {
    if (event.type === 'auxclick' && event.button !== 1) return;
    var anchor = event.target.closest && event.target.closest('a');
    if (!anchor) return;
    var topic = anchor.closest('.topic');
    if (topic) {
      var count = Number(topic.getAttribute('data-count')) || 2;
      award(topicKey(topic), 20 + count * 10, '悬案已调查', anchor, topic);
      return;
    }
    if (anchor.classList.contains('story')) {
      var row = anchor.parentNode;
      // Clones in the reader dialog mirror the stamp of their source row.
      if (row.closest('.reader-list')) row.classList.add('is-read');
      award(storyKey(anchor), 10, '线报已调查', anchor, row);
    }
  }
  document.addEventListener('click', investigate);
  document.addEventListener('auxclick', investigate);
  paintSeen();
  paintHud();

  themeLabel();
  update();
  root.classList.add('enhanced');
})();
