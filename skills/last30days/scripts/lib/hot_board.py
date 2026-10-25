"""Self-contained hot-board page styled as a detective newspaper ("侦探日报").

Cross-platform topics render as case files and each source board as an informant
column. The page stays fully readable without JavaScript; the script only adds
filtering, search, the reader dialog and the small case-solving game.

The small cat sprite is adapted from Jesseovo/Jesseovo's user-supplied, redrawn
profile artwork (scripts/animate_cat.py). Each pose uses the original pixel grid;
CSS moves whole sprites without rotating or deforming them. No runtime imaging
library, network asset, font service or frontend dependency is required.
"""

import base64
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any, Callable, Dict

_ASSETS = Path(__file__).resolve().parent
_LINK = 'target="_blank" rel="noopener noreferrer"'
_ICONS = {
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
    "close": '<path d="m6 6 12 12M6 18 18 6"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "arrow": '<path d="M5 12h14m-5-5 5 5-5 5"/>',
    "external": '<path d="M14 4h6v6m0-6L10 14M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
    "folder": '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/><path d="M3 10h18"/>',
    "news": '<path d="M4 5h13v14H5a1 1 0 0 1-1-1Z"/><path d="M17 9h3v9a1 1 0 0 1-1 1h-2M7 8h7M7 11h7M7 14h4"/>',
    "moon": '<path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
    "github": '<path d="M9 19c-4 1-4-2-6-2m12 5v-4a3.5 3.5 0 0 0-1-2.5c3.4-.4 7-1.6 7-7.5a5.8 5.8 0 0 0-1.6-4A5.4 5.4 0 0 0 19 0s-1.3-.4-4 1.5a14 14 0 0 0-7 0C5.3-.4 4 0 4 0a5.4 5.4 0 0 0-.4 4A5.8 5.8 0 0 0 2 8c0 5.9 3.6 7.1 7 7.5A3.5 3.5 0 0 0 8 18v4" transform="translate(1 1) scale(.9)"/>',
    "tv": '<rect x="3" y="6" width="18" height="15" rx="3"/><path d="m8 2 4 4 4-4M8 12v3m8-3v3m-6 2h4"/>',
    "music": '<path d="M14 3v12a4 4 0 1 1-4-4m4-8c0 4 3 6 7 6"/>',
    "rss": '<path d="M5 11a8 8 0 0 1 8 8M5 4a15 15 0 0 1 15 15"/><circle cx="5" cy="19" r="1" fill="currentColor"/>',
    "spark": '<path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Z"/>',
    "star": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z"/>',
    "badge": '<path d="M12 2 14 5h4v4l3 3-3 3v4h-4l-2 3-2-3H6v-4l-3-3 3-3V5h4Z"/><circle cx="12" cy="12" r="3.2"/>',
}

# Fixed presentation values only; source-provided identifiers never become CSS.
_PLATFORMS = {
    "weibo": ("#b8432c", "#f6e6da", "微"),
    "baidu": ("#3f539a", "#e7eaf3", "百"),
    "douyin": ("#3a342d", "#e9e4d8", "music"),
    "toutiao": ("#b0343a", "#f5e2e1", "头"),
    "bilibili": ("#3f7189", "#e3eef2", "tv"),
    "zhihu": ("#2f6da0", "#e3edf5", "知"),
    "ithome": ("#a3463a", "#f5e5df", "IT"),
    "huxiu": ("#6f6634", "#efeadb", "虎"),
    "sspai": ("#9c4a3f", "#f3e3de", "π"),
    "ifanr": ("#4c665f", "#e5ede9", "A"),
    "solidot": ("#62703f", "#e9eddc", "S"),
    "hackernews": ("#a35a1f", "#f5e6d4", "Y"),
}

_BRAND = '''<svg class="brand-icon" viewBox="0 0 28 28" fill="none" stroke="currentColor" stroke-width="2.6" aria-hidden="true">
<circle cx="11.5" cy="11.5" r="7.5"/><path d="m17 17 8 8" stroke-width="4" stroke-linecap="round"/><path d="M8 9.5a4 4 0 0 1 3.5-2" stroke-width="1.8" stroke-linecap="round"/></svg>'''

_DESK = '''<figure class="hero-art" aria-hidden="true">
<div class="photo"><div class="photo-dots"></div>
<svg class="photo-lamp" viewBox="0 0 120 70"><path d="M8 66 46 6h28l38 60Z" fill="currentColor" opacity=".13"/></svg>
<div class="cat-track"><div class="pixel-cat"></div></div>
<svg class="photo-lens" viewBox="0 0 64 64" fill="none" stroke="currentColor"><circle cx="26" cy="26" r="17" stroke-width="5"/><circle cx="26" cy="26" r="13" fill="currentColor" opacity=".08" stroke="none"/><path d="m39 39 18 18" stroke-width="8" stroke-linecap="round"/><path d="M18 20a10 10 0 0 1 8-5" stroke-width="2.5" stroke-linecap="round"/></svg>
<span class="photo-stamp">机密</span></div>
<figcaption class="art-caption">本报特派员 · 侦探猫 <span>STAFF PHOTO</span></figcaption></figure>'''


def _icon(name: str, extra: str = "") -> str:
    return (
        '<svg class="icon ' + extra + '" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">' + _ICONS[name] + '</svg>'
    )


def _text(value: Any) -> str:
    return escape(str(value), quote=True)


def _group(sid: str, board: Dict[str, Any]) -> str:
    if sid == "hackernews":
        return "global"
    return "news" if board.get("kind") == "feed" else "cn"


def _edition(generated: Any) -> str:
    """Issue number derived from the snapshot date; a dash when it cannot be parsed."""
    try:
        day = datetime.strptime(str(generated)[:10], "%Y-%m-%d").date()
    except ValueError:
        return "—"
    return "{:03d}".format(max(1, (day - date(2025, 1, 1)).days + 1))


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def render_page(data: Dict[str, Any], per_board: int, max_topics: int, site_title: str,
                fmt_hot: Callable[[Any], str], safe_href: Callable[[str], str]) -> str:
    """Render escaped source data; all controls enhance an already readable page."""
    boards = data["boards"]
    topics = data.get("topics") or []
    total = sum(len(b.get("items") or []) for b in boards.values())
    live = sum(1 for b in boards.values() if b.get("items"))
    groups = {"cn": 0, "news": 0, "global": 0}
    for sid, board in boards.items():
        groups[_group(sid, board)] += 1

    def link(url: str) -> str:
        return _text(safe_href(url))

    topic_cards = []
    for idx, topic in enumerate(topics[:max_topics], 1):
        mentions = topic.get("mentions") or []
        categories = sorted({_group(m["platform"], boards.get(m["platform"], {})) for m in mentions})
        keywords = " ".join([topic["title"]] + [m["label"] for m in mentions])
        count = topic.get("platform_count", len(mentions))
        chips = "".join(
            '<a class="chip" href="{}" {}>{}<span>#{}</span></a>'.format(
                link(m.get("url", "")), _LINK, _text(m["label"]), _text(m["rank"]))
            for m in mentions
        )
        topic_cards.append(
            '<article class="topic" data-k="{}" data-groups="{}" data-count="{}">'
            '<div class="case-head"><span class="case-no">悬案 No.{:02d}</span><span class="case-tag">CASE FILE</span></div>'
            '<div class="case-body"><span class="case-stamp">重大案件<b>{}</b>平台</span>'
            '<a class="t" href="{}" {} title="{}">{}</a>'
            '<div class="chips"><span class="chips-label">线报</span>{}</div></div></article>'.format(
                _text(keywords), _text(" ".join(categories)), _int(count, 2), idx, _text(count),
                link(topic.get("url", "")), _LINK, _text(topic["title"]), _text(topic["title"]), chips)
        )

    board_cards = []
    source_tabs = []
    for idx, (sid, board) in enumerate(boards.items()):
        items = (board.get("items") or [])[:per_board]
        label = board.get("label") or sid
        code = board.get("code") or sid
        color, background, symbol = _PLATFORMS.get(sid, ("#4f5e44", "#e7eadb", "rss"))
        badge = _icon(symbol) if symbol in _ICONS else _text(symbol)
        short_label = str(label).replace("热搜", "").replace("热榜", "").strip() or str(label)
        source_tabs.append(
            '<button class="source-tab" type="button" id="source-tab-{}" '
            'data-board="{}" aria-pressed="false" aria-controls="board-card-{}">'
            '<span class="platform-icon" style="--platform:{};--platform-bg:{}" aria-hidden="true">{}</span>'
            '<span class="source-tab-label">{}</span><small class="source-match" hidden></small></button>'.format(
                idx, idx, idx, color, background, badge, _text(short_label))
        )
        list_id = "board-items-{}".format(idx)
        if items:
            rows = []
            for item in items:
                is_board = board.get("kind") == "board"
                heat = fmt_hot(item.get("hot_value")) if is_board else (item.get("label") or "")
                tag = '<span class="tag">{}</span>'.format(_text(item["label"])) if is_board and item.get("label") else ""
                metadata = '<span class="story-meta"><span class="heat">{}</span>{}</span>'.format(_text(heat), tag)
                rank = item.get("rank", "")
                rank_label = "{:02d}".format(rank) if isinstance(rank, int) else str(rank)
                rows.append(
                    '<li data-k="{}"><a class="story" href="{}" {} title="{}">'
                    '<span class="rank">{}</span><span class="story-content"><span class="story-title">{}</span>{}</span></a></li>'.format(
                        _text(item["title"]), link(item.get("url", "")), _LINK, _text(item["title"]),
                        _text(rank_label), _text(item["title"]), metadata)
                )
            body = '<ol id="{}">{}</ol>'.format(list_id, "".join(rows))
            body += (
                '<button class="board-open js-only" type="button" aria-haspopup="dialog" aria-controls="board-reader" '
                'aria-label="调阅{}完整卷宗"><span>调阅全部 {} 条</span>{}</button>'.format(
                    _text(label), len(items), _icon("arrow"))
            )
        else:
            message = str(board.get("error") or "该来源在本次快照中没有返回条目。")
            body = (
                '<div class="board-error"><span class="lost-stamp">线人失联</span><p>这次暂时没有取到内容</p>'
                '<details><summary>查看来源状态</summary><p>{}</p></details></div>'.format(_text(message))
            )
        board_cards.append(
            '<article class="board" id="board-card-{}" data-group="{}" data-k="{}" data-code="{}" aria-labelledby="board-title-{}">'
            '<div class="board-head"><span class="platform-icon" style="--platform:{};--platform-bg:{}" aria-hidden="true">{}</span>'
            '<div class="board-identity"><span class="board-kicker">线人报告</span><h3 id="board-title-{}">{}</h3><span class="code">{}</span></div>'
            '<span class="board-count">{}</span></div>{}</article>'.format(
                idx, _group(sid, board), _text(label), _text(code), idx, color, background, badge,
                idx, _text(label), _text(code), "{} 条".format(len(items)) if items else "未获取", body)
        )

    topic_section = ""
    if topic_cards:
        topic_section = (
            '<section class="topics-section" id="topics-section" aria-labelledby="topics-title">'
            '<div class="section-head"><div class="section-title">{}<h2 id="topics-title">今日悬案</h2>'
            '<span class="section-note">多个平台同时出现的线索，很可能是同一起案件</span></div>'
            '<button class="text-button js-only" id="topics-toggle" type="button" aria-expanded="false" '
            'aria-controls="topics"><span>查看全部 {} 个</span>{}</button></div>'
            '<div class="topics" id="topics">{}</div></section>'.format(
                _icon("folder"), len(topic_cards), _icon("chevron"), "".join(topic_cards))
        )

    filters = '<button type="button" class="filter" data-filter="all" aria-pressed="true">全部<small>{}</small></button>'.format(len(boards))
    for category, label in (("cn", "国内热榜"), ("news", "科技资讯"), ("global", "全球视野")):
        if groups[category]:
            filters += '<button type="button" class="filter" data-filter="{}" aria-pressed="false">{}<small>{}</small></button>'.format(category, label, groups[category])

    if topic_cards:
        extra = "{} 起跨平台悬案浮出水面，{} 路线人发回 {} 条线报".format(len(topic_cards), live, total)
    else:
        extra = "{} 路线人发回 {} 条线报，等你逐条查证".format(live, total)
    filter_note = '<span>专案「{}」</span>'.format(_text(data["topic_filter"])) if data.get("topic_filter") else ""
    style = (_ASSETS / "hot_board.css").read_text(encoding="utf-8")
    script = (_ASSETS / "hot_board.js").read_text(encoding="utf-8")
    sprite = base64.b64encode((_ASSETS / "hot_board_cat.png").read_bytes()).decode("ascii")
    style += '\n:root { --cat-sprite: url("data:image/png;base64,' + sprite + '"); }'
    theme_init = "try{var t=localStorage.getItem('last30days-hot-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}"
    return '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="侦探日报：聚合微博、百度、抖音、B站、知乎、科技资讯与 Hacker News 的热点，把每天的热搜当成悬案来查。">
<title>{title} · {generated}</title>
<script>{theme_init}</script>
<style>{style}</style>
</head>
<body>
<a class="skip" href="#boards-section">跳到线人报告</a>
<div class="wrap">
<header class="nav">
  <a class="brand" href="https://github.com/Jesseovo/last30days-skill-cn" {external}>{brand}<span>last30days<span class="brand-sep"> / </span>热榜</span></a>
  <span class="brand-note">本报讯 · A LITTLE CURIOSITY, EVERY DAY.</span>
  <div class="nav-actions"><a class="nav-link" href="https://github.com/Jesseovo/last30days-skill-cn" {external}>{github}GitHub</a>
    <button class="shift-button js-only" id="theme-toggle" type="button" aria-label="切换夜班">{moon}{sun}<span id="theme-label">夜班</span></button></div>
</header>
<div class="masthead">
  <div class="mast-ears">
    <div class="ear"><small>今日天气</small><b>疑云密布</b></div>
    <div class="nameplate"><div class="np-cn">侦探日报</div><div class="np-en">THE DAILY CLUE</div></div>
    <div class="ear ear-right"><small>零售价</small><b>5¢</b></div>
  </div>
  <div class="mast-rule"><span>EDITION No.{edition}</span><span><time>{generated}</time> 截稿 · 北京时间</span><span>每日一刊 · 5¢</span></div>
</div>
<p class="extra"><span class="extra-burst" aria-hidden="true">号外</span><b>EXTRA! EXTRA!</b><span class="extra-copy">{extra}</span></p>
<main>
<section class="hero" aria-label="本期头条"><div class="hero-copy">
  <div class="eyebrow">本期头条 · FRONT PAGE</div>
  <h1>{title}</h1>
  <p class="deck">今天，世界在聊什么？拿起放大镜，一条条查下去。<span class="caret" aria-hidden="true"></span></p>
  <div class="snapshot"><span><i class="dot" aria-hidden="true"></i><time>{generated}</time> 截稿 · 北京时间</span>
    <span><b>{live}</b> 路线人到岗</span><span><b>{total}</b> 条线报</span>{filter_note}</div>
</div>{desk}</section>
<section class="case-hud js-only" id="case-hud" aria-label="侦探档案">
  <div class="hud-rank"><span class="hud-badge" id="hud-badge" aria-hidden="true">{badge}</span><div><small>侦探等级</small><b id="hud-rank">实习侦探</b></div></div>
  <div class="hud-points"><small>线索积分</small><b id="hud-points">0</b></div>
  <div class="hud-progress"><div class="hud-progress-label"><small>破案进度</small><span id="hud-count">0 / 0</span></div>
    <div class="hud-bar" id="hud-bar" role="progressbar" aria-label="破案进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i id="hud-fill"></i></div>
    <small class="hud-next" id="hud-next">打开任意线报开始调查</small></div>
</section>
<div class="sr-only" id="case-status" role="status" aria-live="polite"></div>
<div class="toolbar js-only">
  <div class="filters" role="group" aria-label="按卷宗分类">{filters}</div>
  <div class="search-box"><label class="search-label" for="q">{search}<span>搜查</span></label><input id="q" type="search" placeholder="输入线索 · AI、游戏、科技…" aria-label="搜查热点或平台" autocomplete="off">
    <button class="search-clear" id="search-clear" type="button" aria-label="清空搜查" hidden>{close}</button></div>
</div>
<noscript><p class="noscript">已展示全部线报；开启 JavaScript 可使用搜查、分类、破案进度和折叠功能。</p></noscript>
{topic_section}
<section class="boards-section" id="boards-section" aria-labelledby="boards-title">
  <div class="section-head"><div class="section-title">{news}<h2 id="boards-title">线人报告</h2><span class="section-note">各平台线人发回的原始线报</span></div>
    <span class="board-summary" id="board-summary" role="status" aria-live="polite">{board_count} 份报告</span></div>
  <div class="source-nav js-only">
    <button class="source-toggle" id="source-toggle" type="button" aria-expanded="false" aria-controls="source-picker">
      <span class="source-current" id="source-current"></span><span class="source-toggle-action"><span id="source-toggle-label">切换线人</span>{chevron}</span>
    </button>
    <div class="source-picker" id="source-picker" hidden>
      <div class="source-picker-head"><span>选择线人</span><small id="source-picker-count"></small></div>
      <div class="source-tabs" role="group" aria-label="选择平台榜单">{source_tabs}</div>
    </div>
  </div>
  <div class="grid">{board_cards}</div>
  <div class="empty js-only" id="empty" hidden><span class="empty-stamp" aria-hidden="true">线索中断</span><h2>没找到相关线索</h2><p>换个关键词再搜查一次，或翻翻其他卷宗。</p><button type="button" class="reset-button" id="reset">撤销搜查，查看全部</button></div>
</section>
</main>
<dialog class="board-reader" id="board-reader" aria-labelledby="reader-title" aria-describedby="reader-context">
  <header class="reader-head"><div id="reader-icon" aria-hidden="true"></div><div class="reader-identity"><div class="eyebrow">线人报告 · 完整卷宗</div><h2 id="reader-title">完整榜单</h2></div>
    <button class="icon-button" id="reader-close" type="button" aria-label="关闭完整卷宗" autofocus>{close}</button></header>
  <p class="reader-context" id="reader-context"></p>
  <ol class="reader-list" id="reader-list"></ol>
  <footer class="reader-footer">{external_icon}<span>点击线报，在新窗口查看来源并记为已调查</span><time>{generated} · 北京时间</time></footer>
</dialog>
<footer class="footer"><div><p>榜单为定时采集快照，排名与热度以来源页面为准。破案进度只保存在你的浏览器里。</p>
  <p>由 <a href="https://github.com/Jesseovo/last30days-skill-cn" {external}>last30days-cn</a> 印制 · 数据来自各平台公开内容</p></div>
  <div class="footer-sign">PRINTED WITH CURIOSITY <span>✦</span><br><a href="https://github.com/Jesseovo" {external}>a little corner by Jesse</a></div></footer>
</div>
<aside class="star-nudge" id="star-nudge" role="region" aria-labelledby="star-title" aria-live="polite" hidden>
  <div class="star-badge" aria-hidden="true">{star}</div>
  <div class="star-copy"><h2 id="star-title">线人求助：给本报点颗 Star</h2><p>让更多侦探发现这份小小日报。</p>
    <a class="star-link" id="star-link" href="https://github.com/Jesseovo/last30days-skill-cn" {external}>{github}<span>去 GitHub Star</span>{external_icon}</a></div>
  <button class="star-close" id="star-close" type="button" aria-label="关闭 Star 提示">{close}</button>
</aside>
<div class="clue-toast" id="clue-toast" aria-hidden="true" hidden></div>
<script>{script}</script>
</body>
</html>'''.format(
        title=_text(site_title), generated=_text(data["generated_at"]), theme_init=theme_init,
        style=style, external=_LINK, brand=_BRAND, github=_icon("github"), moon=_icon("moon", "theme-moon"),
        sun=_icon("sun", "theme-sun"), live=live, total=total, filter_note=filter_note, desk=_DESK,
        edition=_edition(data["generated_at"]), extra=_text(extra), badge=_icon("badge"),
        filters=filters, search=_icon("search"), close=_icon("close"), chevron=_icon("chevron"), external_icon=_icon("external"), topic_section=topic_section,
        news=_icon("news"), board_count=len(boards), board_cards="".join(board_cards), source_tabs="".join(source_tabs),
        star=_icon("star"), script=script)
