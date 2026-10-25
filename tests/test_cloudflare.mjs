import {test} from "node:test";
import assert from "node:assert/strict";
import worker, {signRequest, parsePages, validateVerdict, investigate, DetectiveJobs} from "../scripts/cloudflare/worker.mjs";

test("Tencent TC3 signature matches the independent Python reference vector", async () => {
  const auth = await signRequest("AKIDz8krbsJ5yKBZQpn74WFkmLPx3EXAMPLE", "Gu5t9xGARNpq86cd98joQYCN3EXAMPLE", '{"Query":"test"}', 1551113065);
  assert.ok(auth.endsWith("Signature=e70b2f2d53ae4e51af32c0465f104954c035b8550e29e073ff5fd356449ca185"));
});

test("evidence rejects invalid URLs, invalid dates and malformed pages", () => {
  const evidence = parsePages({Pages: ["broken", {title: "bad", url: "javascript:alert(1)"},
    JSON.stringify({title: "source", url: "https://www.example.com/a", date: "2026/10/20"}),
    {title: "invalid date", url: "https://example.com/b", date: "2026-02-31"}]});
  assert.equal(evidence.length, 2);
  assert.equal(evidence[0].date, "2026-10-20");
  assert.equal(evidence[0].source_domain, "example.com");
  assert.equal(evidence[1].date, null);
});

test("a true or false verdict requires real evidence for every claim", () => {
  const evidence = [{id: "E1", title: "real source", url: "https://example.com/"}];
  const result = validateVerdict({verdict: "真", claims: [{text: "claim", evidence: ["E999"]}],
    candidates: [{name: "invented", evidence: ["E999"]}]}, evidence);
  assert.equal(result.verdict, "没查到可靠来源");
  assert.deepEqual(result.claims[0].sources, []);
  assert.deepEqual(result.candidates, []);
  assert.equal(validateVerdict({verdict: "真", claims: [{text: "supported", evidence: ["E1"]}, {text: "unsupported"}]}, evidence).verdict, "没查到可靠来源");
});

test("health distinguishes deployment from configured search and model services", async () => {
  const response = await worker.fetch(new Request("https://detective.example/api/health"), {});
  assert.deepEqual(await response.json(), {ok: true, search_configured: false, model_configured: false});
});

test("root URL serves the index asset and keeps security headers", async () => {
  let assetPath;
  const response = await worker.fetch(new Request("https://detective.example/"), {
    ASSETS: {fetch: async request => {assetPath = new URL(request.url).pathname; return new Response("index");}},
  });
  assert.equal(assetPath, "/index.html");
  assert.equal(await response.text(), "index");
  assert.match(response.headers.get("Content-Security-Policy"), /frame-ancestors 'none'/);
});

test("cross-site and oversized API requests are blocked before backend execution", async () => {
  let response = await worker.fetch(new Request("https://detective.example/api/check", {
    method: "POST", headers: {Origin: "https://other.example"}, body: "{}"}), {});
  assert.equal(response.status, 403);
  response = await worker.fetch(new Request("https://detective.example/api/check", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: "x".repeat(4097)}), {});
  assert.equal(response.status, 413);
});

test("missing credentials fail explicitly before creating a job", async () => {
  const backend = new DetectiveJobs({storage: {}}, {});
  const response = await backend.fetch(new Request("https://detective.example/api/check", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question: "问题"})}));
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /尚未配置/);
});

test("live pipeline uses returned search evidence and strips invented model citations", async () => {
  const originalFetch = globalThis.fetch;
  const originalTimeout = AbortSignal.timeout;
  // Cloudflare does not expose every Node/browser AbortSignal convenience API.
  AbortSignal.timeout = undefined;
  let llmCalls = 0;
  globalThis.fetch = async (url, options) => {
    assert.equal(options.redirect, "manual");
    assert.ok(options.signal instanceof AbortSignal);
    if (url === "https://wsa.tencentcloudapi.com/") {
      assert.match(options.headers.Authorization, /^TC3-HMAC-SHA256/);
      return Response.json({Response: {Pages: [{title: "真实证据", url: "https://example.com/source", passage: "摘要"}]}});
    }
    llmCalls++;
    const output = llmCalls === 1 ? {claim: "测试", sub_questions: [{query: "测试", question: "测试"}]} :
      {verdict: "真", reasoning: "结果", claims: [{text: "说法", evidence: ["E1", "E999"]}]};
    return Response.json({choices: [{message: {content: JSON.stringify(output)}}]});
  };
  try {
    const stages = [];
    const result = await investigate({TENCENTCLOUD_SECRET_ID: "test-id", TENCENTCLOUD_SECRET_KEY: "test-key", DEEPSEEK_API_KEY: "test"}, "测试", async stage => stages.push(stage));
    assert.equal(result.verdict, "真");
    assert.deepEqual(result.claims[0].evidence, ["E1"]);
    assert.equal(result.claims[0].sources[0].url, "https://example.com/source");
    assert.deepEqual(stages, ["decompose", "search", "judge"]);
    assert.equal(result.search_calls, 1);
  } finally { globalThis.fetch = originalFetch; AbortSignal.timeout = originalTimeout; }
});

function memoryStorage() {
  const values = new Map();
  const store = {
    get: async key => structuredClone(values.get(key)),
    put: async (key, value) => {
      if (typeof key === "object") Object.entries(key).forEach(([k, v]) => values.set(k, structuredClone(v)));
      else values.set(key, structuredClone(value));
    },
    delete: async key => values.delete(key),
    list: async ({prefix}) => new Map([...values].filter(([k]) => k.startsWith(prefix)).map(([k, v]) => [k, structuredClone(v)])),
    transaction: async operation => operation(store),
    setAlarm: async timestamp => {store.alarm = timestamp;},
  };
  return store;
}

test("persisted jobs survive a new coordinator, poll, hit the cache and enforce quotas", async () => {
  const originalFetch = globalThis.fetch;
  let searches = 0;
  globalThis.fetch = async () => {
    searches++;
    return Response.json({Response: {Pages: [{title: "source", url: "https://example.com/source"}]}});
  };
  try {
    const storage = memoryStorage();
    const env = {TENCENTCLOUD_SECRET_ID: "test-id", TENCENTCLOUD_SECRET_KEY: "test-key", PER_MINUTE: "2", PER_DAY: "3"};
    const submit = (ip, question) => new Request("https://detective.example/api/check", {
      method: "POST", headers: {"CF-Connecting-IP": ip, "Content-Type": "application/json"}, body: JSON.stringify({question})});
    let coordinator = new DetectiveJobs({storage}, env);
    const first = await coordinator.fetch(submit("client-a", "测试？"));
    assert.equal(first.status, 202);
    const job = (await first.json()).job;
    coordinator = new DetectiveJobs({storage}, env);
    await coordinator.alarm();
    const status = await coordinator.fetch(new Request(`https://detective.example/api/status/${job}`));
    const completed = await status.json();
    assert.equal(completed.state, "done");
    assert.equal(completed.result.verdict, "说不准");
    assert.equal(completed.result.evidence.length, 1);
    const second = await coordinator.fetch(submit("client-a", "测 试"));
    const secondId = (await second.json()).job;
    const cached = await coordinator.fetch(new Request(`https://detective.example/api/status/${secondId}`));
    assert.equal((await cached.json()).result.from_cache, true);
    assert.equal(searches, 1);
    assert.equal((await coordinator.fetch(submit("client-a", "第三次"))).status, 429);
    assert.equal((await coordinator.fetch(submit("client-b", "测试"))).status, 202);
    assert.equal((await coordinator.fetch(submit("client-c", "测试"))).status, 429);
    assert.equal((await coordinator.fetch(new Request("https://detective.example/api/status/0000000000000000"))).status, 404);
  } finally { globalThis.fetch = originalFetch; }
});
