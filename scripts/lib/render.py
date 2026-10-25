"""Output rendering for Chinese-platform research (last30days CN skill).

Author: Jesse (https://github.com/Jesseovo)

v4: rendering is driven by the source registry (``lib/sources.py``). This
fixes several v3 label bugs (小红书「收藏」显示的是分享数、知乎赞同数从不显示、
公众号名称/头条来源不显示) and adds overseas sources, per-source status with
the data path used, and a dark-mode-aware HTML report.
"""

import json
import os
import tempfile
import zlib
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import schema, sources
from .version import DISPLAY_VERSION

OUTPUT_DIR = Path.home() / ".local" / "share" / "last30days" / "out"

# (attribute, label, kind) — kind "count" prints "1,234点赞", "star" prints "★1,234"
_ENGAGEMENT_FIELDS: Dict[str, Sequence[Tuple[str, str]]] = {
    "weibo": (("likes", "点赞"), ("reposts", "转发"), ("num_comments", "评论")),
    "xiaohongshu": (("likes", "点赞"), ("collects", "收藏"), ("num_comments", "评论"), ("shares", "分享")),
    "bilibili": (("views", "播放"), ("danmaku", "弹幕"), ("num_comments", "评论"), ("favorites", "收藏"), ("likes", "点赞")),
    "zhihu": (("voteups", "赞同"), ("num_comments", "评论"), ("collects", "收藏")),
    "douyin": (("views", "播放"), ("likes", "点赞"), ("num_comments", "评论"), ("shares", "分享")),
    "toutiao": (("reads", "阅读"), ("num_comments", "评论"), ("likes", "点赞"), ("hot_value", "热度")),
    "hackernews": (("score", "points"), ("num_comments", "评论")),
    "github": (("stars", "★"), ("num_comments", "评论")),
    "reddit": (("score", "upvotes"), ("num_comments", "评论")),
    "upstream": (("score", "分"), ("likes", "赞"), ("views", "播放"), ("num_comments", "评论"), ("reposts", "转发")),
}


def _safe_href(url: str) -> str:
    """仅放行 http/https 链接作为 HTML href，拦截 javascript:/data: 等可执行协议。

    抓取/搜索结果中的 URL 不可信，直接写入 href 会造成存储型 XSS（点击执行）。
    非 http(s) 链接一律降级为 ``#``。
    """
    cleaned = (url or "").strip()
    if cleaned.lower().startswith(("http://", "https://")):
        return cleaned
    return "#"


def _items(report: schema.Report, name: str):
    return getattr(report, name, None) or []


def _err(report: schema.Report, name: str):
    return getattr(report, name, None)


def _source_ids(report: schema.Report) -> List[str]:
    """Sources to render, in registry order."""
    active = set(report.active_sources()) if hasattr(report, "active_sources") else set()
    for sid in sources.SOURCES:
        if _items(report, sid) or _err(report, f"{sid}_error"):
            active.add(sid)
    return sources.ordered(active)


def _engine_badge(report: schema.Report) -> str:
    suffix = " · 缓存" if getattr(report, "from_cache", False) else ""
    return f"🌐 last30days-cn v{DISPLAY_VERSION} · 数据截至 {report.range_to}{suffix}"


def _xref_tag(item) -> str:
    """Return ' [同时见于: 微博, 知乎]' if item has cross_refs, else ''."""
    refs = getattr(item, "cross_refs", None)
    if not refs:
        return ""
    names = set()
    for ref_id in refs:
        label = sources.label_for_item_id(str(ref_id))
        if label:
            names.add(label)
    if names:
        return f" [同时见于: {', '.join(sorted(names))}]"
    return ""


def ensure_output_dir():
    """Ensure output directory exists. Supports env override and sandbox fallback."""
    global OUTPUT_DIR
    env_dir = os.environ.get("LAST30DAYS_OUTPUT_DIR")
    if env_dir:
        OUTPUT_DIR = Path(env_dir)

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        OUTPUT_DIR = Path(tempfile.gettempdir()) / "last30days" / "out"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _list_recent_count(items, range_from: str) -> int:
    return sum(1 for it in items if getattr(it, "date", None) and it.date >= range_from)


def _assess_data_freshness(report: schema.Report) -> dict:
    """Assess how much data is actually from the research window."""
    lists = [_items(report, sid) for sid in sources.SOURCES]
    recent = sum(_list_recent_count(lst, report.range_from) for lst in lists)
    total = sum(len(lst) for lst in lists)
    return {
        "total_recent": recent,
        "total_items": total,
        "is_sparse": recent < 5,
        "mostly_evergreen": total > 0 and recent < total * 0.3,
    }


def _fmt_number(value) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def format_engagement(source_id: str, eng) -> str:
    """Render known, non-zero engagement metrics for a source."""
    if not eng:
        return ""
    parts = []
    for attr, label in _ENGAGEMENT_FIELDS.get(source_id, ()):
        value = getattr(eng, attr, None)
        if value in (None, 0, 0.0, ""):
            continue
        if label == "★":
            parts.append(f"★{_fmt_number(value)}")
        elif label.isascii():
            parts.append(f"{_fmt_number(value)} {label}")
        else:
            parts.append(f"{_fmt_number(value)}{label}")
    return f" [{', '.join(parts)}]" if parts else ""


# Backward-compatible helpers (v3 names).
def _fmt_eng_weibo(eng) -> str:
    return format_engagement("weibo", eng)


def _fmt_eng_bilibili(eng) -> str:
    return format_engagement("bilibili", eng)


def _fmt_eng_douyin(eng) -> str:
    return format_engagement("douyin", eng)


def _fmt_eng_xhs(eng) -> str:
    return format_engagement("xiaohongshu", eng)


def _fmt_eng_zhihu(eng) -> str:
    return format_engagement("zhihu", eng)


def _fmt_eng_wechat(eng) -> str:
    return ""


def _one_line(text: str) -> str:
    return " ".join(str(text or "").split())


def _item_title(item) -> str:
    for attr in ("title", "text"):
        value = getattr(item, attr, None)
        if value:
            return _one_line(value)
    return ""


def _item_body(item) -> str:
    for attr in ("text", "desc", "excerpt", "snippet", "abstract", "description"):
        value = getattr(item, attr, None)
        if value:
            return _one_line(value)
    return ""


def _item_author(item) -> str:
    for attr in ("author_name", "author_handle", "channel_name", "author", "source_name", "source_domain"):
        value = getattr(item, attr, None)
        if value:
            return str(value)
    return ""


def _plain_text(item) -> str:
    for attr in ("title", "text", "snippet", "abstract", "excerpt", "desc", "description"):
        value = getattr(item, attr, None)
        if value:
            return str(value)
    return ""


def _who(source_id: str, item) -> str:
    if source_id in ("weibo", "douyin"):
        author = getattr(item, "author_handle", "") or getattr(item, "author_name", "")
        return f"@{author}" if author and not author.startswith(("微博热搜", "抖音热榜")) else (author or "")
    if source_id in ("hackernews", "github", "reddit", "upstream"):
        platform = sources.platform_label(getattr(item, "platform", source_id))
        container = getattr(item, "container", "")
        author = getattr(item, "author", "")
        bits = [platform]
        if container and container.lower() != platform.lower():
            bits.append(container)
        if author:
            bits.append(f"@{author}")
        return " · ".join(bits)
    return _item_author(item)


def _clusters_md_lines(report: schema.Report, limit: int = 8) -> list:
    """跨平台聚合热点（Markdown），无簇时返回空列表。"""
    clusters = getattr(report, "clusters", None) or []
    if not clusters:
        return []
    lines = ["### 🔗 跨平台聚合热点", ""]
    for c in clusters[:limit]:
        srcs = "、".join(c.get("sources", []))
        title = c.get("representative_title", "") or "(无标题)"
        lines.append(f"- **{title}** — 覆盖 {srcs}（{c.get('size', 0)} 条）")
        url = c.get("representative_url", "")
        if url:
            lines.append(f"  {url}")
    lines.append("")
    return lines


def _status_hint(report: schema.Report, source_id: str) -> str:
    status = (getattr(report, "source_status", None) or {}).get(source_id) or {}
    via = status.get("via") or {}
    if not via:
        return ""
    fallback_only = all(str(path).startswith(("site-search", "hot")) for path in via)
    if fallback_only:
        return "*注意：本平台结果全部来自热榜/公开搜索兜底，只有公开链接，缺少完整互动数据与精确日期。*"
    return ""


def _render_item_compact(source_id: str, item) -> List[str]:
    date = getattr(item, "date", None)
    date_str = f" ({date})" if date else " (日期未知)"
    conf = getattr(item, "date_confidence", "high")
    conf_str = f" [日期:{conf}]" if conf != "high" else ""
    eng_str = format_engagement(source_id, getattr(item, "engagement", None))
    who = _who(source_id, item)
    head = f"**{item.id}** (得分:{item.score}) {who}{date_str}{conf_str}{eng_str}{_xref_tag(item)}"
    lines = [head.replace("  ", " ")]

    title = _item_title(item)
    if source_id in ("weibo", "douyin"):
        snippet = title[:200] + ("..." if len(title) > 200 else "")
        lines.append(f"  {snippet}")
    else:
        lines.append(f"  {title[:160]}")
        body = _item_body(item)
        if body and body != title:
            lines.append(f"  {body[:150]}{'...' if len(body) > 150 else ''}")
    lines.append(f"  {item.url}")
    hashtags = getattr(item, "hashtags", None)
    if hashtags:
        lines.append(f"  话题: {' '.join('#' + h for h in hashtags[:8])}")
    if getattr(item, "why_relevant", ""):
        lines.append(f"  *{item.why_relevant}*")
    lines.append("")
    return lines


def render_compact(report: schema.Report, limit: int = 15, missing_keys: str = "none") -> str:
    """Render compact output for the assistant to synthesize."""
    lines = [_engine_badge(report), f"## 研究结果: {report.topic}", ""]
    if getattr(report, "from_cache", False):
        age = getattr(report, "cache_age_hours", None)
        age_text = f"约 {age:.1f} 小时前" if age is not None else "时间未知"
        lines.append(f"*缓存命中：{age_text}生成。使用 `--refresh` 可强制刷新。*")
        lines.append("")

    freshness = _assess_data_freshness(report)
    if freshness["is_sparse"]:
        lines.append("**⚠️ 近期数据较少** — 研究时间窗内可确认的讨论不多。")
        lines.append(f"仅 {freshness['total_recent']} 条可确认日期在 {report.range_from} 至 {report.range_to} 之间。")
        lines.append("下列结果可能含较早或常青内容，请向用户如实说明时效性。")
        lines.append("")

    lines.append(f"**日期范围:** {report.range_from} ~ {report.range_to}")
    lines.append(f"**模式:** {report.mode}")
    search_topic = getattr(report, "search_topic", "")
    if search_topic and search_topic != report.topic:
        lines.append(f"**平台检索词:** {search_topic}")
    lines.append("")

    if missing_keys != "none":
        lines.append("*💡 提示: 补齐各平台登录态/API Key 可多源交叉验证。*")
        lines.append("")

    lines.extend(_clusters_md_lines(report))

    for sid in _source_ids(report):
        spec = sources.get(sid)
        items = _items(report, sid)
        error = _err(report, f"{sid}_error")
        if not items and not error:
            continue
        lines.extend([f"### {spec.section}", ""])
        if not items:
            lines.extend([f"**错误:** {error}", ""])
            continue
        hint = _status_hint(report, sid)
        if hint:
            lines.extend([hint, ""])
        for item in items[:limit]:
            lines.extend(_render_item_compact(sid, item))

    return "\n".join(lines)


def render_quality_nudge(quality: dict) -> str:
    """Render the quality score nudge block."""
    nudge_text = quality.get("nudge_text")
    if not nudge_text:
        return ""
    return "\n".join(["---", f"**🔍 研究覆盖度: {quality['score_pct']}%**", "", nudge_text, ""])


def _via_text(status: Dict[str, Any]) -> str:
    via = status.get("via") or {}
    if not via:
        return ""
    parts = [f"{path}×{count}" if count > 1 else path for path, count in via.items()]
    return f"（路径: {', '.join(parts)}）"


def render_source_status(report: schema.Report, source_info: dict = None) -> str:
    """Render the source status footer."""
    source_info = source_info or {}
    lines = ["---", "**来源:**"]
    statuses = getattr(report, "source_status", None) or {}
    for sid in _source_ids(report):
        label = sources.label(sid)
        items = _items(report, sid)
        error = _err(report, f"{sid}_error")
        status = statuses.get(sid, {})
        elapsed = status.get("elapsed")
        timing = f" · {elapsed:.0f}s" if isinstance(elapsed, (int, float)) and elapsed >= 1 else ""
        if items:
            raw_count = status.get("raw_count")
            kept = f"（原始 {raw_count} 条，按时间窗/相关性保留）" if raw_count and raw_count != len(items) else ""
            lines.append(f"  ✅ {label}: {len(items)} 条{kept}{_via_text(status)}{timing}")
        elif status.get("state") == "timeout":
            lines.append(f"  ⏱️ {label}: 超时 — {error or ''}".rstrip(" —"))
        elif error:
            lines.append(f"  ❌ {label}: {error}")
        else:
            lines.append(f"  ⚠️ {label}: 0 条（检索成功但时间窗内无相关结果）")
    reason = source_info.get("baidu_skip_reason") or source_info.get("web_skip_reason")
    if reason:
        lines.append(f"  ⚡ 百度: {reason}")
    lines.append("")
    return "\n".join(lines)


def render_context_snippet(report: schema.Report) -> str:
    """Render reusable context snippet."""
    lines = [
        f"# 上下文: {report.topic}（{report.range_from} ~ {report.range_to}）",
        "",
        f"*生成时间: {report.generated_at[:10]} | 模式: {report.mode}*",
        "",
        "## 主要来源",
        "",
    ]
    all_items = []
    for sid in sources.SOURCES:
        for item in _items(report, sid)[:5]:
            text = _plain_text(item)
            all_items.append((item.score, sources.label(sid), (text[:50] + "...") if len(text) > 50 else text, item.url))
    all_items.sort(key=lambda x: -x[0])
    for _score, label, text, url in all_items[:8]:
        lines.append(f"- [{label}] {text} — {url}")
    clusters = getattr(report, "clusters", None) or []
    if clusters:
        lines.extend(["", "## 跨平台热点", ""])
        for c in clusters[:5]:
            lines.append(f"- {c.get('representative_title', '')}（{'、'.join(c.get('sources', []))}）")
    lines.extend(["", "## 摘要", "", "*完整报告见 report.md / report.html。*", ""])
    return "\n".join(lines)


def render_full_report(report: schema.Report) -> str:
    """Render the full markdown report."""
    lines = [
        _engine_badge(report),
        "",
        f"# {report.topic} — 近 {_window_days(report)} 天研究报告",
        "",
        f"**生成时间:** {report.generated_at}",
        f"**日期范围:** {report.range_from} ~ {report.range_to}",
        f"**模式:** {report.mode}",
        "",
    ]
    lines.extend(_clusters_md_lines(report))

    for sid in _source_ids(report):
        spec = sources.get(sid)
        items = _items(report, sid)
        error = _err(report, f"{sid}_error")
        if not items and not error:
            continue
        lines.extend([f"## {spec.section}", ""])
        if not items:
            lines.extend([f"> 错误：{error}", ""])
            continue
        for item in items:
            title = _item_title(item)
            lines.append(f"### {item.id}: {title[:80]}")
            lines.append("")
            who = _who(sid, item)
            if who:
                lines.append(f"- **作者/来源:** {who}")
            lines.append(f"- **链接:** {item.url}")
            lines.append(f"- **日期:** {item.date or '未知'} (置信: {getattr(item, 'date_confidence', 'low')})")
            lines.append(f"- **得分:** {item.score}/100")
            eng = format_engagement(sid, getattr(item, "engagement", None)).strip(" []")
            if eng:
                lines.append(f"- **互动:** {eng}")
            refs = _xref_tag(item).strip()
            if refs:
                lines.append(f"- **交叉验证:** {refs.strip('[]')}")
            if getattr(item, "why_relevant", ""):
                lines.append(f"- **相关性:** {item.why_relevant}")
            body = _item_body(item)
            if body and body != title:
                lines.extend(["", f"> {body[:400]}"])
            lines.append("")

    lines.append(render_source_status(report))
    return "\n".join(lines)


def _window_days(report: schema.Report) -> int:
    from datetime import datetime
    try:
        delta = datetime.strptime(report.range_to, "%Y-%m-%d") - datetime.strptime(report.range_from, "%Y-%m-%d")
        return max(1, delta.days)
    except (TypeError, ValueError):
        return 30


def write_outputs(report: schema.Report):
    """Write report.json, report.md, report.html, and last30days.context.md."""
    ensure_output_dir()
    with open(OUTPUT_DIR / "report.json", "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    with open(OUTPUT_DIR / "report.md", "w", encoding="utf-8") as f:
        f.write(render_full_report(report))
    with open(OUTPUT_DIR / "report.html", "w", encoding="utf-8") as f:
        f.write(render_html_report(report))
    with open(OUTPUT_DIR / "last30days.context.md", "w", encoding="utf-8") as f:
        f.write(render_context_snippet(report))


def get_context_path() -> str:
    """Get path to context file."""
    return str(OUTPUT_DIR / "last30days.context.md")


def get_html_path() -> str:
    """Get path to the generated HTML report."""
    return str(OUTPUT_DIR / "report.html")


def _source_meta() -> Dict[str, Tuple[str, str]]:
    return {sid: (spec.label, spec.code) for sid, spec in sources.SOURCES.items()}


# Kept for compatibility with v3 callers/tests.
SOURCE_META = _source_meta()


def _engagement_total(item) -> int:
    eng = getattr(item, "engagement", None)
    if not eng:
        return 0
    total = 0
    for attr in ("views", "likes", "reposts", "shares", "collects", "favorites", "num_comments", "replies",
                 "reads", "danmaku", "voteups", "score", "stars"):
        value = getattr(eng, attr, None)
        if isinstance(value, (int, float)):
            total += int(value)
    hot = getattr(item, "hot_value", None)
    if isinstance(hot, (int, float)):
        total += int(hot)
    return total


def _collect_ranked_items(report: schema.Report, limit: int = 30):
    rows = []
    for source in SOURCE_META:
        for item in _items(report, source):
            rows.append((source, item))
    rows.sort(key=lambda pair: (getattr(pair[1], "score", 0), _engagement_total(pair[1])), reverse=True)
    return _diversify_ranked(rows, limit)


def _diversify_ranked(rows, limit: int, min_per_source: int = 2, relevance_floor: float = 0.25):
    """Keep top-ranked items while reserving a small floor for relevant minor sources."""
    if len(rows) <= limit:
        return rows

    selected = list(rows[:limit])
    selected_ids = {id(item) for _, item in selected}
    source_counts: Dict[str, int] = {}
    for source, _ in selected:
        source_counts[source] = source_counts.get(source, 0) + 1

    rank_index = {id(item): idx for idx, (_, item) in enumerate(rows)}

    for source in SOURCE_META:
        if source_counts.get(source, 0) >= min_per_source:
            continue
        eligible = [
            (src, item) for src, item in rows
            if src == source
            and id(item) not in selected_ids
            and getattr(item, "relevance", 0.0) >= relevance_floor
        ]
        for candidate in eligible:
            if source_counts.get(source, 0) >= min_per_source:
                break
            replace_idx = None
            for idx in range(len(selected) - 1, -1, -1):
                replace_source, _replace_item = selected[idx]
                if replace_source == source:
                    continue
                if source_counts.get(replace_source, 0) > min_per_source:
                    replace_idx = idx
                    break
            if replace_idx is None:
                break
            removed_source, removed_item = selected[replace_idx]
            selected_ids.remove(id(removed_item))
            source_counts[removed_source] -= 1
            selected[replace_idx] = candidate
            selected_ids.add(id(candidate[1]))
            source_counts[source] = source_counts.get(source, 0) + 1

    selected.sort(key=lambda pair: rank_index[id(pair[1])])
    return selected[:limit]


HTML_STYLE = """
:root {
  --paper:#efe8d6; --paper2:#e3dac3; --paperD:#cfc4a8; --ink:#1b1815; --ink2:#3a342d;
  --gray:#8d857a; --lgray:#bdb4a3; --red:#d42a2f; --redD:#9e1b22; --gold:#e2b23c; --cream:#f8f3e6;
  --cork:#b98a55; --corkD:#8e6338; --dot:rgba(27,24,21,.16); --ok:#2f6b3a;
  --serif:"Bodoni 72","Didot","Playfair Display","Songti SC","STSong","SimSun",serif;
  --cond:Impact,"Arial Narrow Bold","Haettenschweiler","PingFang SC","Microsoft YaHei",sans-serif;
  --type:"Courier New",Courier,"PingFang SC","Microsoft YaHei",monospace;
  --body:"Songti SC","STSong","Noto Serif SC","SimSun",Georgia,serif;
}
@media (prefers-color-scheme: dark) {
  :root { --paper:#1e1b17; --paper2:#26221d; --paperD:#3a342c; --ink:#efe6d2; --ink2:#cfc4ad;
          --gray:#9a917f; --lgray:#5a5348; --red:#e5484d; --redD:#ff7b7f; --gold:#e8bd4f; --cream:#2b2721;
          --cork:#5a4126; --corkD:#3d2b18; --dot:rgba(239,230,210,.08); --ok:#7fc08a; }
  .stamp { mix-blend-mode:normal; }
  body::after { mix-blend-mode:screen; opacity:.08; }
}
* { box-sizing:border-box; }
html { background:var(--paper); }
body { margin:0; color:var(--ink); font-family:var(--body); line-height:1.5;
  background:radial-gradient(var(--dot) 1px, transparent 1.3px) 0 0/7px 7px, var(--paper); }
body::after { content:""; position:fixed; inset:0; pointer-events:none; z-index:50; opacity:.22; mix-blend-mode:multiply;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.55'/%3E%3C/svg%3E"); }
a { color:inherit; }
.page { max-width:1180px; margin:0 auto; padding:0 clamp(12px,3vw,32px) 40px; }

/* EXTRA! EXTRA! ticker */
.extra { background:var(--red); color:#f8f3e6; border-bottom:3px solid var(--ink); overflow:hidden; white-space:nowrap;
  font-family:var(--cond); letter-spacing:.08em; font-size:15px; padding:6px 0; }
.extra-track { display:inline-block; padding-left:100%; animation:ticker 40s linear infinite; }
.extra-track span { margin-right:48px; }
.extra-track b { color:#ffd25e; }
@keyframes ticker { to { transform:translateX(-100%); } }

/* Masthead */
.masthead { text-align:center; padding:22px 0 0; }
.mast-top,.mast-info { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;
  font-family:var(--type); font-size:12px; text-transform:uppercase; letter-spacing:.12em; color:var(--ink2); }
.mast-top { border-bottom:1px solid var(--ink); padding-bottom:6px; }
.mast-title { font-family:var(--serif); font-style:italic; font-weight:900; font-size:clamp(38px,8vw,100px);
  line-height:.95; letter-spacing:-.01em; margin:14px 0 6px; }
.mast-title .dot { color:var(--red); font-style:normal; }
.mast-sub { font-family:var(--cond); font-size:clamp(12px,1.5vw,16px); letter-spacing:.32em; text-transform:uppercase; margin-bottom:10px; }
.rule-double { border-top:4px solid var(--ink); border-bottom:1px solid var(--ink); height:8px; }
.mast-info { padding:7px 0; border-bottom:3px solid var(--ink); }
.mast-info b { color:var(--red); }

/* Dossier hero */
.dossier { position:relative; margin:34px 0 10px; }
.folder-tab { display:inline-block; background:var(--gold); color:#1b1815; border:3px solid var(--ink); border-bottom:none;
  padding:6px 22px 4px; font-family:var(--cond); letter-spacing:.18em; font-size:15px; border-radius:6px 6px 0 0; margin-left:24px; }
.folder { position:relative; background:var(--paper2); border:3px solid var(--ink); box-shadow:8px 8px 0 var(--ink);
  padding:clamp(18px,3vw,36px); display:grid; grid-template-columns:minmax(0,1.5fr) minmax(0,1fr); gap:28px; }
.folder::before { content:""; position:absolute; inset:0; pointer-events:none; opacity:.6;
  background:radial-gradient(var(--dot) 1.4px, transparent 1.8px) 0 0/9px 9px;
  -webkit-mask-image:linear-gradient(120deg, transparent 40%, #000); mask-image:linear-gradient(120deg, transparent 40%, #000); }
.subject { position:relative; z-index:1; }
.file-label { font-family:var(--type); font-size:13px; letter-spacing:.14em; text-transform:uppercase; color:var(--redD); font-weight:700; }
.dossier h1 { font-family:var(--serif); font-weight:900; font-size:clamp(34px,6.2vw,80px); line-height:1.04; margin:10px 0 14px; overflow-wrap:anywhere; }
.redact { display:inline-block; background:var(--ink); height:.36em; width:2.4em; vertical-align:middle; margin-left:.25em; }
.lede { font-size:clamp(15px,1.6vw,19px); color:var(--ink2); max-width:640px; margin:0; }
.lede::first-letter { font-family:var(--serif); font-weight:900; font-size:3em; float:left; line-height:.85; margin:4px 8px 0 0; color:var(--red); }
.fields { position:relative; z-index:1; display:grid; grid-template-columns:1fr 1fr; border:3px solid var(--ink); background:var(--cream); align-self:end; }
.field { padding:12px 14px; border-right:1px dashed var(--ink); border-bottom:1px dashed var(--ink); }
.field:nth-child(2n) { border-right:none; }
.field:nth-last-child(-n+2) { border-bottom:none; }
.field small { display:block; font-family:var(--type); font-size:11px; letter-spacing:.1em; color:var(--gray); text-transform:uppercase; }
.field strong { display:block; font-family:var(--cond); font-weight:400; font-size:clamp(30px,4.4vw,52px); line-height:1; margin-top:4px; }
.field.hot strong { color:var(--red); }
.stamp { position:absolute; z-index:3; top:-26px; right:26px; transform:rotate(-12deg);
  border:5px double var(--red); color:var(--red); background:rgba(212,42,47,.04); padding:8px 16px; font-family:var(--cond);
  font-size:clamp(20px,2.6vw,30px); letter-spacing:.14em; text-align:center; line-height:1.05; opacity:.88;
  mix-blend-mode:multiply; border-radius:4px; animation:slam .55s cubic-bezier(.2,1.6,.4,1) .35s both; }
.stamp small { display:block; font-family:var(--type); font-size:11px; letter-spacing:.2em; }
@keyframes slam { 0% { opacity:0; transform:rotate(-24deg) scale(3); } 70% { opacity:.95; transform:rotate(-10deg) scale(.92); } 100% { opacity:.88; transform:rotate(-12deg) scale(1); } }
.clip { position:absolute; top:-16px; left:46%; width:22px; height:58px; border:3px solid var(--gray); border-radius:12px; z-index:4; }
.dateline { display:flex; justify-content:space-between; flex-wrap:wrap; gap:10px; margin:22px 0 0; padding:10px 0;
  border-top:3px solid var(--ink); border-bottom:1px solid var(--ink); font-family:var(--type); font-size:13px; }
.dateline b { font-family:var(--cond); font-weight:400; letter-spacing:.06em; font-size:16px; }

/* Detective note */
.notice { position:relative; margin:26px auto 0; max-width:640px; background:#f7e27a; color:#1b1815; padding:16px 20px 14px 22px;
  font-family:var(--type); font-size:14px; border:2px solid var(--ink); box-shadow:5px 5px 0 var(--ink); transform:rotate(-1deg); }
.notice b { font-family:var(--cond); font-weight:400; letter-spacing:.1em; color:#9e1b22; margin-right:8px; }

/* Section headers */
.section { margin-top:46px; }
.sec-head { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; border-top:4px solid var(--ink); border-bottom:1px solid var(--ink);
  padding:8px 0 6px; margin-bottom:22px; }
.sec-head h2 { margin:0; font-family:var(--serif); font-style:italic; font-weight:900; font-size:clamp(26px,3.8vw,44px); line-height:1.05; }
.sec-no { background:var(--ink); color:var(--paper); font-family:var(--cond); letter-spacing:.12em; padding:3px 10px; font-size:14px; }
.sec-head .meta { margin-left:auto; font-family:var(--type); font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--gray); }

/* Corkboard with red string */
.corkboard { position:relative; border:3px solid var(--ink); box-shadow:8px 8px 0 var(--ink); padding:40px clamp(18px,3vw,40px) 30px;
  background:radial-gradient(rgba(0,0,0,.2) 1px, transparent 1.6px) 0 0/5px 5px,
    radial-gradient(rgba(255,255,255,.14) 1px, transparent 1.6px) 2px 3px/7px 7px, var(--cork);
  outline:10px solid var(--corkD); outline-offset:-13px; overflow:hidden; }
.leads { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:38px 34px; }
.lead { position:relative; background:#f8f3e6; color:#1b1815; border:2px solid #1b1815; padding:22px 16px 14px; box-shadow:4px 5px 0 rgba(0,0,0,.45); }
.lead:nth-child(3n+1) { transform:rotate(-1.6deg); }
.lead:nth-child(3n+2) { transform:rotate(1.2deg); }
.lead:nth-child(3n) { transform:rotate(-.6deg); }
.lead::before { content:""; position:absolute; top:-9px; left:50%; width:18px; height:18px; margin-left:-9px; border-radius:50%;
  background:radial-gradient(circle at 35% 35%, #ff9a9a, #d42a2f 45%, #9e1b22); border:2px solid #1b1815; z-index:3; }
.lead::after { content:""; position:absolute; top:0; left:50%; width:calc(100% + 34px); height:3px; background:#d42a2f;
  transform-origin:0 50%; transform:rotate(8deg); box-shadow:0 2px 1px rgba(0,0,0,.35); z-index:2; pointer-events:none; }
.lead:last-child::after { display:none; }
.lead-tag { font-family:var(--type); font-size:11px; letter-spacing:.14em; color:#9e1b22; text-transform:uppercase; }
.lead h3 { font-family:var(--body); font-size:17px; line-height:1.35; margin:6px 0 10px; overflow-wrap:anywhere; }
.lead-src { font-family:var(--type); font-size:12px; color:#3a342d; }
.lead-meta { display:flex; justify-content:space-between; align-items:end; gap:10px; margin-top:10px; border-top:1px dashed #1b1815; padding-top:8px; }
.lead-meta strong { font-family:var(--cond); font-weight:400; font-size:30px; line-height:1; color:#d42a2f; }
.lead a { display:block; margin-top:8px; font-family:var(--type); font-size:12px; color:#9e1b22; overflow-wrap:anywhere; }

/* Informant reports + evidence tags */
.report-block { margin-bottom:36px; }
.report-head { display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:18px; font-family:var(--type); font-size:13px; }
.report-head h3 { margin:0; font-family:var(--cond); font-weight:400; font-size:24px; letter-spacing:.06em; }
.report-head .code { border:2px solid var(--ink); padding:1px 8px; font-family:var(--cond); letter-spacing:.14em; }
.report-head .line { flex:1; min-width:40px; border-top:2px dashed var(--ink); }
.evidence { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:22px; }
.tag { position:relative; background:var(--cream); border:3px solid var(--ink); box-shadow:6px 6px 0 var(--ink);
  padding:18px 18px 16px 44px; display:flex; flex-direction:column; transition:transform .15s; }
.tag:nth-child(odd) { transform:rotate(-.5deg); } .tag:nth-child(even) { transform:rotate(.45deg); }
.tag:hover { transform:translate(-2px,-2px); }
.tag::before { content:""; position:absolute; left:11px; top:20px; width:14px; height:14px; border-radius:50%;
  background:var(--paper); border:3px solid var(--ink); box-shadow:inset 0 0 0 2px var(--gold); }
.tag::after { content:""; position:absolute; left:0; top:0; bottom:0; width:6px; background:var(--red); }
.tag-top { display:flex; justify-content:space-between; align-items:start; gap:10px; }
.tag-no { font-family:var(--cond); font-size:22px; letter-spacing:.06em; line-height:1; }
.tag-no small { display:block; font-family:var(--type); font-size:10px; letter-spacing:.18em; color:var(--gray); margin-bottom:3px; }
.suspect { text-align:right; font-family:var(--type); font-size:10px; letter-spacing:.14em; color:var(--gray); }
.suspect b { display:block; font-family:var(--cond); font-weight:400; font-size:36px; line-height:.9; color:var(--red); letter-spacing:0; }
.tag-meta { display:flex; gap:6px 14px; flex-wrap:wrap; margin:10px 0 8px; font-family:var(--type); font-size:12px; color:var(--ink2); }
.tag h4 { margin:0; font-size:17px; line-height:1.42; font-weight:700; overflow-wrap:anywhere; }
.memo { margin:10px 0 0; font-family:var(--type); font-size:12.5px; color:var(--ink2); border-left:3px solid var(--gold); padding-left:8px; }
.memo b { color:var(--redD); }
.heat { margin-top:12px; display:flex; align-items:center; gap:10px; font-family:var(--type); font-size:12px; }
.heat-label { font-family:var(--cond); letter-spacing:.1em; background:var(--ink); color:var(--paper); padding:1px 6px; white-space:nowrap; }
.heat-bar { flex:1; height:10px; border:2px solid var(--ink); background:var(--paper2); min-width:50px; }
.heat-bar i { display:block; height:100%; background:repeating-linear-gradient(90deg, var(--red) 0 5px, var(--redD) 5px 7px); }
.heat-text { margin-top:4px; font-family:var(--type); font-size:11.5px; color:var(--gray); overflow-wrap:anywhere; }
.tag a { margin-top:auto; padding-top:12px; font-family:var(--type); font-size:12px; color:var(--redD); overflow-wrap:anywhere; text-decoration:none; }
.tag a:hover,.tag a:focus-visible { text-decoration:underline; }
.empty-case { border:3px dashed var(--ink); padding:28px; text-align:center; font-family:var(--type); }

/* Informant roster */
.roster { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:16px; }
.mug { position:relative; background:var(--cream); border:3px solid var(--ink); box-shadow:5px 5px 0 var(--ink); padding:12px 14px; min-height:132px; display:flex; flex-direction:column; }
.mug.error,.mug.timeout { background:repeating-linear-gradient(-45deg, var(--cream) 0 10px, var(--paper2) 10px 20px); }
.mug-code { font-family:var(--cond); letter-spacing:.14em; font-size:13px; background:var(--ink); color:var(--paper); align-self:flex-start; padding:2px 8px; }
.mug-name { font-family:var(--serif); font-weight:900; font-size:22px; margin-top:8px; }
.mug-count { margin-top:auto; font-family:var(--cond); font-size:44px; line-height:.9; }
.mug-count small { font-family:var(--type); font-size:11px; letter-spacing:.1em; margin-left:6px; color:var(--gray); }
.mug-state { position:absolute; right:8px; bottom:12px; transform:rotate(-8deg); border:2px solid currentColor; padding:1px 6px;
  font-family:var(--cond); font-size:13px; letter-spacing:.1em; }
.ok { --st:var(--ok); } .empty { --st:var(--gray); } .error,.timeout { --st:var(--red); }
.mug-state,.log-state { color:var(--st); }

/* Investigation log */
.log { border:3px solid var(--ink); background:var(--cream); box-shadow:6px 6px 0 var(--ink); font-family:var(--type); font-size:13px; }
.log-row { display:grid; grid-template-columns:76px 120px 100px 80px minmax(0,1fr); gap:10px; padding:9px 14px; border-bottom:1px dashed var(--ink); align-items:center; }
.log-row:last-child { border-bottom:none; }
.log-row.head { background:var(--ink); color:var(--paper); font-family:var(--cond); letter-spacing:.12em; }
.log-state { font-family:var(--cond); letter-spacing:.08em; }
.log-note { color:var(--ink2); overflow-wrap:anywhere; }

.colophon { max-width:1180px; margin:0 auto; padding:18px clamp(12px,3vw,32px) 36px; font-family:var(--type); font-size:12px; color:var(--gray); text-align:center; }
.colophon .rule-double { margin-bottom:12px; }

@media (prefers-reduced-motion: reduce) {
  .stamp,.extra-track { animation:none; }
  .extra-track { padding-left:0; }
  .tag { transition:none; }
}
@media (max-width:820px) {
  .folder { grid-template-columns:1fr; }
  .stamp { right:10px; }
  .log-row { grid-template-columns:64px 1fr 90px; }
  .log-row .log-count,.log-row .log-note { grid-column:2 / -1; }
  .log-row.head .log-count,.log-row.head .log-note { display:none; }
}
@media print {
  body::after,.extra { display:none; }
  .stamp { animation:none; }
  .folder,.tag,.mug,.log,.corkboard { box-shadow:none; }
  .tag,.lead { break-inside:avoid; transform:none !important; }
}
"""

_LOG_STATE_TEXT = {"ok": "已取证", "empty": "无线索", "error": "线人失联", "timeout": "线人失联"}


def _case_number(topic: str) -> str:
    """Stable 5-digit case number derived from the topic."""
    return f"{zlib.crc32((topic or '').encode('utf-8')) % 100000:05d}"


def _source_state(report: schema.Report, source: str, statuses: Dict[str, Any]) -> str:
    if _items(report, source):
        return "ok"
    if (statuses.get(source) or {}).get("state") == "timeout":
        return "timeout"
    if _err(report, f"{source}_error"):
        return "error"
    return "empty"


def render_html_report(report: schema.Report) -> str:
    """Render the research report as a newsprint detective "case file"."""
    ranked = _collect_ranked_items(report)
    meta = _source_meta()
    total = sum(len(_items(report, source)) for source in meta)
    shown_sources = [sid for sid in _source_ids(report)] or list(sources.CN_SOURCE_IDS)
    active_sources = [(source, len(_items(report, source))) for source in meta if _items(report, source)]
    top_score = getattr(ranked[0][1], "score", 0) if ranked else 0
    freshness = _assess_data_freshness(report)
    generated = escape(report.generated_at[:19].replace("T", " "))
    statuses = getattr(report, "source_status", None) or {}
    clusters = getattr(report, "clusters", None) or []
    case_no = _case_number(report.topic)
    topic = escape(report.topic)
    range_from = escape(report.range_from)
    range_to = escape(report.range_to)

    # 线人名册 + 调查日志
    roster_cards = []
    log_rows = []
    for source in shown_sources:
        cn, code = meta[source]
        count = len(_items(report, source))
        err = _err(report, f"{source}_error")
        status = statuses.get(source, {}) or {}
        state = _source_state(report, source, statuses)
        state_text = _LOG_STATE_TEXT[state]
        roster_cards.append(
            f'<div class="mug {state}"><span class="mug-code">{escape(code)}</span>'
            f'<div class="mug-name">{escape(cn)}</div>'
            f'<div class="mug-count">{count}<small>件证物</small></div>'
            f'<span class="mug-state">{state_text}</span></div>'
        )
        if state in ("error", "timeout") and err:
            short = str(err) if len(str(err)) <= 80 else str(err)[:78] + "…"
            note = f'<span title="{escape(str(err), quote=True)}">{escape(short)}</span>'
        elif state == "timeout":
            note = "线人超时未回报"
        elif state == "empty":
            note = "检索成功，时间窗内无相关线索"
        else:
            note = escape(_via_text(status).strip("（）"))
        elapsed = status.get("elapsed")
        timing = f" · {elapsed:.0f}s" if isinstance(elapsed, (int, float)) and elapsed >= 1 else ""
        log_rows.append(
            f'<div class="log-row {state}"><span>{escape(code)}</span><span>{escape(cn)}</span>'
            f'<span class="log-state">{state_text}</span>'
            f'<span class="log-count">{count} 件{timing}</span><span class="log-note">{note}</span></div>'
        )

    # 证物：按线人（平台）分组，编号沿用全局排名
    max_heat = max([_engagement_total(item) for _, item in ranked] or [0])
    grouped: Dict[str, List[str]] = {}
    for idx, (source, item) in enumerate(ranked, start=1):
        cn, code = meta[source]
        text = _plain_text(item)
        snippet = text[:220] + ("..." if len(text) > 220 else "")
        author = _who(source, item)
        date = getattr(item, "date", None) or "日期未知"
        score_value = getattr(item, "score", 0)
        reason = getattr(item, "why_relevant", "") or ""
        eng = format_engagement(source, getattr(item, "engagement", None)).strip(" []")
        url = getattr(item, "url", "") or "#"
        heat = _engagement_total(item)
        pct = max(4, int(round(100 * heat / max_heat))) if heat and max_heat else 0
        memo = f'<p class="memo"><b>侦探批注：</b>{escape(reason)}</p>' if reason else ""
        witness = f"<span>目击者 {escape(author)}</span>" if author else ""
        heat_text = f'<div class="heat-text">{escape(eng)}</div>' if eng else ""
        grouped.setdefault(source, []).append(
            '<article class="tag">'
            '<div class="tag-top">'
            f'<div class="tag-no"><small>EVIDENCE</small>证物 #{idx:02d}</div>'
            f'<div class="suspect">嫌疑分<b>{escape(str(score_value))}</b></div>'
            '</div>'
            f'<div class="tag-meta"><span>{escape(code)}</span><span>{escape(date)}</span>{witness}</div>'
            f'<h4>{escape(snippet or url)}</h4>'
            f'{memo}'
            f'<div class="heat"><span class="heat-label">热度指数</span>'
            f'<span class="heat-bar" aria-hidden="true"><i style="width:{pct}%"></i></span>'
            f'<span>{_fmt_number(heat) if heat else "—"}</span></div>'
            f'{heat_text}'
            f'<a href="{escape(_safe_href(url), quote=True)}" target="_blank" rel="noopener noreferrer">调取原始证据 → {escape(url)}</a>'
            '</article>'
        )

    report_blocks = []
    for source, cards in grouped.items():
        cn, code = meta[source]
        report_blocks.append(
            '<div class="report-block">'
            f'<div class="report-head"><span class="code">{escape(code)}</span><h3>线人报告 · {escape(cn)}</h3>'
            f'<span class="line"></span><span>呈交 {len(cards)} 件证物</span></div>'
            f'<div class="evidence">{"".join(cards)}</div>'
            '</div>'
        )
    evidence_html = "".join(report_blocks) or '<div class="empty-case">现场一片空白：本案暂未搜集到任何证物。</div>'

    source_summary = "、".join(f"{meta[s][0]} {n}" for s, n in active_sources) or "暂无线人回报"
    sparse_note = ""
    if freshness["is_sparse"]:
        sparse_note = ('<div class="notice"><b>侦探手记</b>近期可确认的证据较少，'
                       '请在最终分析中明确说明时效性和覆盖限制。</div>')

    cluster_section = ""
    if clusters:
        leads = []
        for n, c in enumerate(clusters[:8], start=1):
            c_sources = "、".join(c.get("sources", []))
            c_title = c.get("representative_title", "") or "(无标题)"
            c_url = c.get("representative_url", "") or ""
            link = (f'<a href="{escape(_safe_href(c_url), quote=True)}" target="_blank" '
                    f'rel="noopener noreferrer">{escape(c_url)}</a>') if c_url else ""
            leads.append(
                '<li class="lead">'
                f'<div class="lead-tag">LEAD #{n:02d} · 关联 ×{escape(str(c.get("size", 0)))}</div>'
                f'<h3>{escape(c_title)}</h3>'
                f'<div class="lead-src">交叉印证：{escape(c_sources)}</div>'
                f'<div class="lead-meta"><span class="lead-src">涉及平台</span><strong>{len(c.get("sources", []))}</strong></div>'
                f'{link}'
                '</li>'
            )
        cluster_section = (
            '<section class="section">'
            '<div class="sec-head"><span class="sec-no">FILE 02</span><h2>关联线索</h2>'
            '<span class="meta">cross-source leads · red string board</span></div>'
            f'<div class="corkboard"><ul class="leads">{"".join(leads)}</ul></div>'
            '</section>'
        )

    ticker = "".join([
        f"<span><b>EXTRA! EXTRA!</b> 侦探日报号外：「{topic}」调查档案公开</span>",
        f"<span>证物 {total} 件 · 线人 {len(active_sources)} 名回报</span>",
        f"<span>最高嫌疑分 <b>{escape(str(top_score))}</b></span>",
        f"<span>关联线索 {len(clusters)} 条</span>",
        f"<span>调查期间 {range_from} — {range_to}</span>",
    ]) * 2
    version = escape(DISPLAY_VERSION)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>调查档案 · {topic} - last30days-cn</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<div class="extra" aria-hidden="true"><div class="extra-track">{ticker}</div></div>
<main class="page">
  <header class="masthead">
    <div class="mast-top"><span>Vol. {version}</span><span>北京时间 · Beijing Edition</span><span>Price ¥0.00</span></div>
    <div class="mast-title">侦探日报 <span class="dot">·</span> THE DAILY CLUE</div>
    <div class="mast-sub">All the clues fit to print</div>
    <div class="rule-double"></div>
    <div class="mast-info"><span>CASE No. <b>{case_no}</b></span><span>Late Edition · {generated}</span><span>调查期间 {range_from} — {range_to}</span></div>
  </header>

  <section class="dossier">
    <span class="folder-tab">CASE FILE · 调查档案</span>
    <div class="folder">
      <span class="clip" aria-hidden="true"></span>
      <div class="stamp" role="img" aria-label="机密 · 已结案">机密 · 已结案<small>CLASSIFIED · CLOSED</small></div>
      <div class="subject">
        <div class="file-label">FILE 01 · 调查对象 / SUBJECT</div>
        <h1>{topic}<span class="redact" aria-hidden="true"></span></h1>
        <p class="lede">本档案汇总 {range_from} 至 {range_to} 期间各平台线人的回报。证物按相关性、时效与热度排序，跨平台关联线索已钉上软木板，可直接浏览、归档或打印。</p>
      </div>
      <div class="fields">
        <div class="field"><small>证物总数 / Evidence</small><strong>{total}</strong></div>
        <div class="field"><small>线人回报 / Informants</small><strong>{len(active_sources)}</strong></div>
        <div class="field hot"><small>最高嫌疑分 / Top score</small><strong>{escape(str(top_score))}</strong></div>
        <div class="field"><small>时间窗内可确认 / In window</small><strong>{freshness["total_recent"]}</strong></div>
      </div>
    </div>
    <div class="dateline"><b>线人回报汇总</b><span>{escape(source_summary)}</span></div>
  </section>
  {sparse_note}
  {cluster_section}
  <section class="section">
    <div class="sec-head"><span class="sec-no">FILE 03</span><h2>证物陈列</h2><span class="meta">informant reports · ranked evidence</span></div>
    {evidence_html}
  </section>
  <section class="section">
    <div class="sec-head"><span class="sec-no">FILE 04</span><h2>线人名册</h2><span class="meta">informant roster</span></div>
    <div class="roster">{''.join(roster_cards)}</div>
  </section>
  <section class="section">
    <div class="sec-head"><span class="sec-no">FILE 05</span><h2>调查日志</h2><span class="meta">investigation log</span></div>
    <div class="log">
      <div class="log-row head"><span>代号</span><span>线人</span><span>状态</span><span class="log-count">证物</span><span class="log-note">取证路径 / 备注</span></div>
      {''.join(log_rows)}
    </div>
  </section>
</main>
<footer class="colophon"><div class="rule-double"></div>侦探日报 THE DAILY CLUE · last30days-cn v{version} · CASE No. {case_no} · 本档案于本地生成，证据链接均指向原始出处。</footer>
</body>
</html>"""
