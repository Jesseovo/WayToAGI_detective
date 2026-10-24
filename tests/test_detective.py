"""侦探模式：元宝搜索封装、大模型客户端、调查引擎、网页接口（全部不联网）。"""
import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import pytest

from lib import detective, detective_web, http, llm, yuanbao

CONFIG = {
    "TENCENTCLOUD_SECRET_ID": "AKIDz8krbsJ5yKBZQpn74WFkmLPx3EXAMPLE",
    "TENCENTCLOUD_SECRET_KEY": "Gu5t9xGARNpq86cd98joQYCN3EXAMPLE",
    "DEEPSEEK_API_KEY": "sk-test",
}


def page(title, url, date="2026/10/20 09:30:00", site="新华网", authority=4, passage="摘要"):
    return json.dumps({
        "title": title, "url": url, "passage": passage, "date": date,
        "site": site, "score": 0.9, "authority_level": authority,
    }, ensure_ascii=False)


# --- 元宝搜索 --------------------------------------------------------------

def test_tc3_signature_matches_reference_vector():
    # 向量由按腾讯云文档步骤独立重算得到，使用文档里的示例密钥
    auth = yuanbao.sign_request(
        CONFIG["TENCENTCLOUD_SECRET_ID"], CONFIG["TENCENTCLOUD_SECRET_KEY"],
        b'{"Query":"test"}', 1551113065,
    )
    assert auth == (
        "TC3-HMAC-SHA256 Credential=AKIDz8krbsJ5yKBZQpn74WFkmLPx3EXAMPLE/2019-02-25/wsa/tc3_request, "
        "SignedHeaders=content-type;host;x-tc-action, "
        "Signature=e70b2f2d53ae4e51af32c0465f104954c035b8550e29e073ff5fd356449ca185"
    )


def test_parse_pages_decodes_nested_json_and_normalizes():
    response = {"Pages": [
        page("标题一", "https://www.xinhuanet.com/a", date="2026/10/20 09:30:00"),
        "not json",
        json.dumps({"title": "没有链接"}),
        page("标题二", "https://example.com/b", date="", site=""),
    ]}
    items = yuanbao.parse_pages(response)
    assert [i["title"] for i in items] == ["标题一", "标题二"]
    assert items[0]["date"] == "2026-10-20"
    assert items[0]["date_confidence"] == "high"
    assert items[0]["authority"] == 4
    assert items[1]["date"] is None
    assert items[1]["source_domain"] == "example.com"


def test_search_pro_sends_signed_request_without_leaking_secret():
    captured = {}

    def fake_request(method, url, headers=None, data=None, **kw):
        captured["headers"], captured["data"], captured["url"] = headers, data, url
        return {"Response": {"Pages": [], "RequestId": "r1"}}

    with patch.object(http, "request", side_effect=fake_request):
        yuanbao.search_pro("北京天气", CONFIG["TENCENTCLOUD_SECRET_ID"], CONFIG["TENCENTCLOUD_SECRET_KEY"], cnt=10)
    assert captured["url"] == "https://wsa.tencentcloudapi.com/"
    assert captured["headers"]["X-TC-Action"] == "SearchPro"
    assert captured["headers"]["X-TC-Version"] == "2025-05-08"
    assert json.loads(captured["data"].decode("utf-8")) == {"Query": "北京天气", "Cnt": 10}
    assert CONFIG["TENCENTCLOUD_SECRET_KEY"] not in json.dumps(captured["headers"])


def test_search_pro_falls_back_when_edition_rejects_params():
    calls = []

    def fake_request(method, url, headers=None, data=None, **kw):
        body = json.loads(data.decode("utf-8"))
        calls.append(body)
        if "Cnt" in body:
            return {"Response": {"Error": {"Code": "InvalidParameter", "Message": "不支持 Cnt"}, "RequestId": "r"}}
        return {"Response": {"Pages": [page("ok", "https://a.com/x")], "RequestId": "r"}}

    with patch.object(http, "request", side_effect=fake_request):
        resp = yuanbao.search_pro("q", "id", "key", cnt=20)
    assert len(calls) == 2 and "Cnt" not in calls[1]
    assert len(yuanbao.parse_pages(resp)) == 1


def test_search_pro_raises_on_api_error():
    err = {"Response": {"Error": {"Code": "ResourceNotFound", "Message": "未开通"}, "RequestId": "r"}}
    with patch.object(http, "request", return_value=err):
        with pytest.raises(yuanbao.YuanbaoError) as info:
            yuanbao.search_pro("q", "id", "key")
    assert "ResourceNotFound" in str(info.value)


# --- 大模型客户端 ----------------------------------------------------------

def test_parse_json_object_tolerates_fences_and_noise():
    assert llm.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json_object('好的:{"a": 2} 以上') == {"a": 2}
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("没有 json")
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("[1, 2]")


def test_chat_json_retries_on_empty_content_then_succeeds():
    replies = iter(["", '{"ok": true}'])

    def fake_post(url, payload, headers=None, **kw):
        assert url == "https://api.deepseek.com/chat/completions"
        assert headers["Authorization"] == "Bearer sk-test"
        assert payload["response_format"] == {"type": "json_object"}
        return {"choices": [{"message": {"content": next(replies)}}]}

    with patch.object(http, "post", side_effect=fake_post):
        assert llm.chat_json(CONFIG, "返回 json", "hi") == {"ok": True}


def test_chat_requires_key():
    with pytest.raises(llm.LLMError):
        llm.chat({}, [{"role": "user", "content": "x"}])


# --- 反幻觉校验 ------------------------------------------------------------

EVIDENCE = [
    {"id": "E1", "title": "官方辟谣", "url": "https://a.gov.cn/1", "source_domain": "a.gov.cn", "date": "2026-10-01"},
    {"id": "E2", "title": "媒体报道", "url": "https://b.com/2", "source_domain": "b.com", "date": "2026-10-02"},
]


def test_validate_drops_unknown_evidence_ids():
    raw = {"verdict": "假", "reasoning": "r", "claims": [{"text": "说法", "evidence": ["E1", "E99"]}]}
    out = detective.validate_verdict(raw, EVIDENCE)
    assert out["verdict"] == "假"
    assert out["claims"][0]["evidence"] == ["E1"]
    assert any("不存在" in n for n in out["notes"])


def test_validate_downgrades_verdict_without_valid_evidence():
    raw = {"verdict": "真", "reasoning": "编的", "claims": [{"text": "说法", "evidence": ["E42"]}]}
    out = detective.validate_verdict(raw, EVIDENCE)
    assert out["verdict"] == "没查到可靠来源"


def test_validate_rejects_unknown_verdict_and_keeps_uncertain():
    out = detective.validate_verdict({"verdict": "大概是真的", "claims": []}, EVIDENCE)
    assert out["verdict"] == "说不准"
    out = detective.validate_verdict({"verdict": "说不准", "claims": []}, EVIDENCE)
    assert out["verdict"] == "说不准"


def test_candidates_need_real_evidence_and_are_capped():
    raw = {
        "verdict": "说不准", "claims": [],
        "candidates": [
            {"name": "女法医", "why": "2005 年王海燕主演", "evidence": ["E1", "E50"]},
            {"name": "凭空编的剧", "why": "x", "evidence": ["E50"]},
            {"name": "", "evidence": ["E1"]},
        ] + [{"name": "剧%d" % i, "why": "", "evidence": ["E2"]} for i in range(10)],
    }
    out = detective.validate_verdict(raw, EVIDENCE)
    names = [c["name"] for c in out["candidates"]]
    assert names[0] == "女法医" and out["candidates"][0]["evidence"] == ["E1"]
    assert "凭空编的剧" not in names
    assert len(names) == detective.MAX_CANDIDATES
    assert any("凭空编的剧" in n for n in out["notes"])


def test_cross_check_filters_irrelevant_folk_items():
    from types import SimpleNamespace
    good = SimpleNamespace(url="https://v.example.com/1", title="女法医 电视剧", date="2026-10-01", relevance=0.4)
    junk = SimpleNamespace(url="https://v.example.com/2", title="完全无关的内容", date="2026-10-01", relevance=0.0)
    from lib import pipeline
    with patch.object(pipeline, "run_sources", return_value={"baidu": {"items": []}}), \
            patch.object(pipeline, "process_results", return_value={"baidu": [good, junk]}):
        folk = detective.cross_check(CONFIG, "那个讲法医的女主剧叫什么")
    assert [f["url"] for f in folk] == ["https://v.example.com/1"]


# --- 调查流程 --------------------------------------------------------------

def fake_search_pro(pages_by_query):
    def run(query, *a, **kw):
        return {"Pages": pages_by_query.get(query, []), "RequestId": "r"}
    return run


def test_no_evidence_means_no_llm_verdict_call():
    plan = {"claim": "c", "sub_questions": [{"question": "q", "query": "q", "fresh": False}], "used_llm": True}
    with patch.object(detective, "decompose", return_value=plan), \
            patch.object(yuanbao, "search_pro", side_effect=fake_search_pro({})), \
            patch.object(detective, "cross_check", return_value=[]), \
            patch.object(llm, "chat_json", side_effect=AssertionError("不应调用大模型")):
        result = detective.investigate(CONFIG, "一个查不到的问题")
    assert result["verdict"] == "没查到可靠来源"
    assert result["evidence"] == []


def test_full_flow_cites_only_real_sources():
    plan = {
        "claim": "隔夜开水致癌",
        "sub_questions": [
            {"question": "隔夜开水有亚硝酸盐吗", "query": "隔夜开水 亚硝酸盐", "fresh": False},
            {"question": "有没有致癌证据", "query": "隔夜开水 致癌", "fresh": False},
        ],
        "used_llm": True,
    }
    pages = {
        "隔夜开水 亚硝酸盐": [page("科普一", "https://sci.example.cn/a", authority=5)],
        "隔夜开水 致癌": [page("科普一", "https://sci.example.cn/a", authority=5),
                      page("自媒体", "https://blog.example.com/b", authority=1)],
    }
    verdict = {"verdict": "假", "reasoning": "权威来源未发现致癌证据",
               "claims": [{"text": "隔夜开水不致癌", "evidence": ["E1", "E77"]}], "conflicts": []}
    with patch.object(detective, "decompose", return_value=plan), \
            patch.object(yuanbao, "search_pro", side_effect=fake_search_pro(pages)), \
            patch.object(detective, "cross_check", return_value=[]), \
            patch.object(llm, "chat_json", return_value=verdict):
        result = detective.investigate(CONFIG, "隔夜开水千万别喝")
    assert result["verdict"] == "假"
    assert [e["url"] for e in result["evidence"]][0] == "https://sci.example.cn/a"  # 权威度高的排前面
    assert len(result["evidence"]) == 2  # 重复链接已合并
    cited = result["claims"][0]["sources"]
    assert [s["url"] for s in cited] == ["https://sci.example.cn/a"]
    assert result["search_calls"] == 2


def test_missing_search_keys_is_a_clear_error():
    with patch.object(detective, "decompose", return_value={
            "claim": "c", "sub_questions": [{"question": "q", "query": "q", "fresh": False}], "used_llm": False}):
        with pytest.raises(detective.DetectiveError) as info:
            detective.investigate({"DEEPSEEK_API_KEY": "x"}, "问题")
    assert "TENCENTCLOUD" in str(info.value)


def test_refusal_from_decompose_propagates():
    with patch.object(llm, "chat_json", return_value={"refuse": True, "refuse_reason": "涉及时政"}):
        with pytest.raises(detective.RefusedError):
            detective.decompose(CONFIG, "某某政策怎么看")


def test_decompose_falls_back_without_llm():
    plan = detective.decompose({}, "楼下火锅店今天开门吗")
    assert plan["used_llm"] is False
    assert plan["sub_questions"][0]["query"] == "楼下火锅店今天开门吗"


def test_question_length_and_empty_checks():
    with pytest.raises(detective.DetectiveError):
        detective.investigate(CONFIG, "   ")
    with pytest.raises(detective.DetectiveError):
        detective.investigate(CONFIG, "x" * 500)


def test_llm_payload_disables_thinking_and_pins_temperature():
    seen = {}

    def fake_post(url, payload, headers=None, **kw):
        seen.update(payload)
        return {"choices": [{"message": {"content": "{}"}}]}

    with patch.object(http, "post", side_effect=fake_post):
        llm.chat(CONFIG, [{"role": "user", "content": "json"}])
    assert seen["thinking"] == {"type": "disabled"}
    assert seen["temperature"] == 0


def test_evidence_order_is_stable_regardless_of_search_order():
    a = page("A", "https://a.example.com/1", authority=3)
    b = page("B", "https://b.example.com/1", authority=3)
    sub = [{"question": "q", "query": "q", "fresh": False}]
    orders = []
    for pages in ([a, b], [b, a]):
        with patch.object(yuanbao, "search_pro", side_effect=fake_search_pro({"q": pages})):
            ev = detective.gather_evidence(CONFIG, [dict(s) for s in sub], detective._Counter())
        orders.append([(e["id"], e["url"]) for e in ev])
    assert orders[0] == orders[1]


def test_evidence_found_by_more_sub_questions_ranks_higher():
    shared = page("共同", "https://z.example.com/shared", authority=2)
    single = page("单个", "https://a.example.com/single", authority=2)
    subs = [{"question": "q1", "query": "q1", "fresh": False}, {"question": "q2", "query": "q2", "fresh": False}]
    with patch.object(yuanbao, "search_pro", side_effect=fake_search_pro({"q1": [single, shared], "q2": [shared]})):
        ev = detective.gather_evidence(CONFIG, subs, detective._Counter())
    assert ev[0]["url"] == "https://z.example.com/shared"


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    from lib import cache
    monkeypatch.setenv("LAST30DAYS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    return tmp_path


def _fake_fresh(verdict="假"):
    calls = {"n": 0}

    def run(config, question, progress, with_cross_check):
        calls["n"] += 1
        return {"question": question, "verdict": verdict, "search_calls": 3, "checked_at": "2026-10-24 16:00"}
    return run, calls


def test_cache_hit_skips_search_and_normalizes_question(isolated_cache):
    run, calls = _fake_fresh()
    with patch.object(detective, "_investigate_fresh", side_effect=run):
        first = detective.investigate(CONFIG, "隔夜开水能喝吗？")
        second = detective.investigate(CONFIG, " 隔夜开水 能喝吗 ")
    assert calls["n"] == 1
    assert first["from_cache"] is False
    assert second["from_cache"] is True and second["verdict"] == "假"


def test_refresh_bypasses_and_overwrites_cache(isolated_cache):
    run, calls = _fake_fresh("假")
    with patch.object(detective, "_investigate_fresh", side_effect=run):
        detective.investigate(CONFIG, "问题甲")
    run2, calls2 = _fake_fresh("说不准")
    with patch.object(detective, "_investigate_fresh", side_effect=run2):
        refreshed = detective.investigate(CONFIG, "问题甲", refresh=True)
        again = detective.investigate(CONFIG, "问题甲")
    assert calls2["n"] == 1
    assert refreshed["from_cache"] is False and refreshed["verdict"] == "说不准"
    assert again["from_cache"] is True and again["verdict"] == "说不准"


def test_errors_are_not_cached(isolated_cache):
    def boom(*a, **kw):
        raise detective.DetectiveError("元宝搜索调用失败")
    with patch.object(detective, "_investigate_fresh", side_effect=boom):
        with pytest.raises(detective.DetectiveError):
            detective.investigate(CONFIG, "问题乙")
    run, calls = _fake_fresh()
    with patch.object(detective, "_investigate_fresh", side_effect=run):
        detective.investigate(CONFIG, "问题乙")
    assert calls["n"] == 1


def test_use_cache_false_never_reads_or_writes(isolated_cache):
    run, calls = _fake_fresh()
    with patch.object(detective, "_investigate_fresh", side_effect=run):
        detective.investigate(CONFIG, "问题丙", use_cache=False)
        detective.investigate(CONFIG, "问题丙", use_cache=False)
    assert calls["n"] == 2
    assert list(isolated_cache.glob("*.json")) == []


# --- 网页 ------------------------------------------------------------------

@pytest.fixture
def server():
    jobs = detective_web.JobStore()
    limiter = detective_web.RateLimiter(per_minute=2, per_day=3)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), detective_web.make_handler(CONFIG, jobs, limiter))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _req(url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def test_web_serves_page_with_strict_csp(server):
    status, headers, body = _req(server + "/")
    assert status == 200 and "AI 侦探".encode("utf-8") in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in headers["Content-Security-Policy"].split("style-src")[0]
    status, _h, js = _req(server + "/app.js")
    assert status == 200 and b"textContent" in js and b"innerHTML" not in js


def test_web_check_flow_and_rate_limit(server):
    fake = {"question": "q", "verdict": "说不准"}
    with patch.object(detective, "investigate", return_value=fake):
        status, _h, body = _req(server + "/api/check", {"question": "隔夜开水能喝吗"})
        assert status == 202
        job = json.loads(body)["job"]
        for _ in range(50):
            _s, _h, raw = _req(server + "/api/status/" + job)
            state = json.loads(raw)
            if state["state"] != "running":
                break
            threading.Event().wait(0.05)
        assert state["state"] == "done" and state["result"] == fake
        assert _req(server + "/api/check", {"question": "第二次"})[0] == 202
        assert _req(server + "/api/check", {"question": "第三次"})[0] == 429


def test_web_rejects_bad_requests(server):
    req = urllib.request.Request(server + "/api/check", data=b"not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(req, timeout=5)
    assert info.value.code == 400
    assert _req(server + "/api/status/zzzz")[0] == 404
    assert _req(server + "/nope")[0] == 404


def test_rate_limiter_daily_cap():
    limiter = detective_web.RateLimiter(per_minute=100, per_day=2)
    assert limiter.allow("a")[0] and limiter.allow("b")[0]
    ok, reason = limiter.allow("c")
    assert not ok and "额度" in reason
