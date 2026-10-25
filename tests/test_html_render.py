import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from lib import render, schema


def test_render_html_report_is_detective_case_file():
    report = schema.create_report("AI 编程助手", "2026-05-01", "2026-05-31", "all")
    report.wechat = [
        schema.WechatItem(
            id="WX1",
            title="测试文章",
            snippet="这是一条测试摘要",
            url="https://example.com/a",
            source_name="测试公众号",
            date="2026-05-20",
            why_relevant="命中主题关键词",
            score=88,
        )
    ]

    html = render.render_html_report(report)

    assert "<!doctype html>" in html
    assert "AI 编程助手" in html
    assert "测试文章" in html
    assert "WECHAT" in html
    # newsprint detective framing
    assert "侦探日报" in html and "THE DAILY CLUE" in html
    assert "EXTRA! EXTRA!" in html
    assert "调查档案" in html and "CASE FILE" in html
    assert "机密 · 已结案" in html
    assert "线人报告" in html
    assert "证物 #01" in html
    assert "热度指数" in html
    assert "侦探批注" in html and "命中主题关键词" in html
    assert "调查日志" in html and "已取证" in html
    # palette, halftone, motion safety, dark mode
    assert "#efe8d6" in html and "#d42a2f" in html
    assert "radial-gradient" in html
    assert "prefers-reduced-motion" in html
    assert "prefers-color-scheme: dark" in html
    assert "#002FA7" not in html
    assert "<script" not in html


def test_html_case_number_is_stable():
    a = render.render_html_report(schema.create_report("同一主题", "2026-05-01", "2026-05-31", "all"))
    b = render.render_html_report(schema.create_report("同一主题", "2026-05-01", "2026-05-31", "all"))
    no = render._case_number("同一主题")
    assert len(no) == 5 and no.isdigit()
    assert f"CASE No. <b>{no}</b>" in a and f"CASE No. <b>{no}</b>" in b


def test_html_investigation_log_states():
    report = schema.create_report("线索", "2026-05-01", "2026-05-31", "all")
    report.baidu = [schema.BaiduItem(id="BD1", title="百度", snippet="", url="https://b.test",
                                     source_domain="x", score=50, date="2026-05-20")]
    report.weibo_error = "HTTP 412 <b>blocked</b>"
    report.zhihu_error = "timed out"
    report.source_status = {
        "baidu": {"state": "ok", "count": 1},
        "weibo": {"state": "error", "count": 0},
        "zhihu": {"state": "timeout", "count": 0},
        "bilibili": {"state": "empty", "count": 0},
    }
    html = render.render_html_report(report)
    assert '<div class="log-row ok">' in html
    assert '<div class="log-row error">' in html
    assert '<div class="log-row timeout">' in html
    assert '<div class="log-row empty">' in html
    assert "无线索" in html and "线人失联" in html
    assert "<b>blocked</b>" not in html
    assert "&lt;b&gt;blocked&lt;/b&gt;" in html


def test_html_clusters_render_as_corkboard_leads():
    report = schema.create_report("关联", "2026-05-01", "2026-05-31", "all")
    report.clusters = [{
        "representative_title": "<i>同一事件</i>",
        "representative_url": "javascript:alert(1)",
        "sources": ["微博", "知乎"],
        "size": 3,
    }]
    html = render.render_html_report(report)
    assert "关联线索" in html and 'class="corkboard"' in html
    assert "LEAD #01" in html and "×3" in html
    assert "&lt;i&gt;同一事件&lt;/i&gt;" in html
    assert 'href="javascript:' not in html


def test_write_outputs_creates_html_report(tmp_path):
    report = schema.create_report("测试主题", "2026-05-01", "2026-05-31", "all")
    report.baidu = [
        schema.BaiduItem(
            id="BD1",
            title="百度测试结果",
            snippet="测试摘要",
            url="https://example.com/b",
            source_domain="example.com",
            date="2026-05-21",
            why_relevant="相关",
            score=77,
        )
    ]

    old_output_dir = render.OUTPUT_DIR
    old_env = os.environ.get("LAST30DAYS_OUTPUT_DIR")
    os.environ["LAST30DAYS_OUTPUT_DIR"] = str(tmp_path)
    try:
        render.write_outputs(report)
        html_path = Path(render.get_html_path())
        assert html_path.exists()
        assert html_path.read_text(encoding="utf-8").startswith("<!doctype html>")
    finally:
        render.OUTPUT_DIR = old_output_dir
        if old_env is None:
            os.environ.pop("LAST30DAYS_OUTPUT_DIR", None)
        else:
            os.environ["LAST30DAYS_OUTPUT_DIR"] = old_env


def test_collect_ranked_items_gives_relevant_small_sources_a_floor():
    report = schema.create_report("AI 编程助手", "2026-05-01", "2026-05-31", "all")
    report.weibo = [
        schema.WeiboItem(id=f"WB{i}", text=f"微博{i}", url="", author_handle=f"a{i}", score=90, relevance=0.9)
        for i in range(40)
    ]
    report.zhihu = [
        schema.ZhihuItem(id=f"ZH{i}", title=f"知乎{i}", excerpt="", url="", author=f"z{i}", score=50, relevance=0.5)
        for i in range(2)
    ]

    ranked = render._collect_ranked_items(report, limit=30)
    ranked_ids = {item.id for _, item in ranked}
    assert {"ZH0", "ZH1"} <= ranked_ids


def test_collect_ranked_items_does_not_floor_low_relevance_sources():
    report = schema.create_report("AI 编程助手", "2026-05-01", "2026-05-31", "all")
    report.weibo = [
        schema.WeiboItem(id=f"WB{i}", text=f"微博{i}", url="", author_handle=f"a{i}", score=90, relevance=0.9)
        for i in range(40)
    ]
    report.zhihu = [
        schema.ZhihuItem(id=f"ZH{i}", title=f"知乎{i}", excerpt="", url="", author=f"z{i}", score=50, relevance=0.05)
        for i in range(2)
    ]

    ranked = render._collect_ranked_items(report, limit=30)
    ranked_ids = {item.id for _, item in ranked}
    assert "ZH0" not in ranked_ids
