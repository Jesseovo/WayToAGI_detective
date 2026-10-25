// Edge adapter for lib/detective.py. UI and model prompts are built from source.
// Durable Object storage keeps jobs, limits and six-hour caches across restarts.
import prompts from "../../dist/cloudflare-prompts.mjs";

const VERDICTS = ["真", "假", "说不准", "没查到可靠来源"];
const MAX_BODY = 4096;
const TTL = 30 * 60 * 1000;
const CACHE_TTL = 6 * 3600 * 1000;
const CONFIG_ERROR = "查证服务尚未配置元宝搜索密钥，请联系站点维护者完成配置。";
const HEADERS = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
};
const json = (data, status = 200) => Response.json(data, { status, headers: HEADERS });
const clean = (value, length) => String(value || "").trim().slice(0, length);
const list = value => Array.isArray(value) ? value : [];
const encoder = new TextEncoder();
const bytes = value => typeof value === "string" ? encoder.encode(value) : value;
const hex = value => [...new Uint8Array(value)].map(x => x.toString(16).padStart(2, "0")).join("");
const digest = async value => hex(await crypto.subtle.digest("SHA-256", bytes(value)));
const hmac = async (key, message) => {
  const imported = await crypto.subtle.importKey("raw", bytes(key), {name: "HMAC", hash: "SHA-256"}, false, ["sign"]);
  return crypto.subtle.sign("HMAC", imported, bytes(message));
};
const searchReady = env => Boolean(env.TENCENTCLOUD_SECRET_ID && env.TENCENTCLOUD_SECRET_KEY);
const modelReady = env => Boolean(env.LLM_API_KEY || env.DEEPSEEK_API_KEY);
const dateKey = () => new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
const reportUpstream = (stage, error, env = {}) => {
  let message = String(error?.message || "").slice(0, 300);
  for (const key of ["TENCENTCLOUD_SECRET_ID", "TENCENTCLOUD_SECRET_KEY", "TENCENTCLOUD_TOKEN", "DEEPSEEK_API_KEY", "LLM_API_KEY"]) {
    if (env[key]) message = message.replaceAll(env[key], "[redacted]");
  }
  console.warn(JSON.stringify({
  event: "detective_upstream_error", stage,
  status: Number.isInteger(error?.status) ? error.status : null,
  code: /^[A-Za-z0-9_.-]{1,100}$/.test(error?.code || "") ? error.code : null,
  type: error?.name === "TimeoutError" ? "timeout" : "upstream",
  error_name: /^[A-Za-z]{1,40}$/.test(error?.name || "") ? error.name : null,
  location: String(error?.stack || "").split("\n").filter(line => /^\s+at /.test(line)).slice(0, 3),
  message,
}));
};

export async function signRequest(id, key, payload, timestamp) {
  const date = new Date(timestamp * 1000).toISOString().slice(0, 10);
  const signed = "content-type;host;x-tc-action";
  const canonical = ["POST", "/", "", "content-type:application/json; charset=utf-8\nhost:wsa.tencentcloudapi.com\nx-tc-action:searchpro\n", signed, await digest(payload)].join("\n");
  const scope = `${date}/wsa/tc3_request`;
  const toSign = ["TC3-HMAC-SHA256", timestamp, scope, await digest(canonical)].join("\n");
  const dateKey = await hmac("TC3" + key, date);
  const serviceKey = await hmac(dateKey, "wsa");
  const signingKey = await hmac(serviceKey, "tc3_request");
  return `TC3-HMAC-SHA256 Credential=${id}/${scope}, SignedHeaders=${signed}, Signature=${hex(await hmac(signingKey, toSign))}`;
}

async function postJSON(url, headers, payload, timeout = 60000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
  const response = await fetch(url, {
    method: "POST", headers: {"Content-Type": "application/json; charset=utf-8", ...headers},
    body: typeof payload === "string" ? payload : JSON.stringify(payload),
    signal: controller.signal, redirect: "manual",
  });
  if (!response.ok) {
    const error = new Error(`上游服务暂时不可用（HTTP ${response.status}），请稍后重试`);
    error.status = response.status;
    throw error;
  }
  return await response.json();
  } finally { clearTimeout(timer); }
}

async function searchPro(env, query, fresh, calls) {
  const payload = {Query: query, Cnt: 10};
  if (fresh) payload.Freshness = "d30";
  async function run() {
    calls.count++;
    const body = JSON.stringify(payload);
    const timestamp = Math.floor(Date.now() / 1000);
    const headers = {
      "Authorization": await signRequest(env.TENCENTCLOUD_SECRET_ID, env.TENCENTCLOUD_SECRET_KEY, body, timestamp),
      "X-TC-Action": "SearchPro", "X-TC-Timestamp": String(timestamp), "X-TC-Version": "2025-05-08",
    };
    if (env.TENCENTCLOUD_TOKEN) headers["X-TC-Token"] = env.TENCENTCLOUD_TOKEN;
    const data = await postJSON("https://wsa.tencentcloudapi.com/", headers, body, 20000);
    if (!data.Response) throw new Error("元宝搜索返回了无法识别的响应");
    return data.Response;
  }
  let response = await run();
  if (String(response.Error?.Code).endsWith("InvalidParameter")) {
    delete payload.Cnt;
    response = await run();
  }
  if (response.Error) {
    const error = new Error("元宝搜索调用失败，请稍后重试");
    error.code = response.Error.Code;
    throw error;
  }
  let pages = parsePages(response);
  if (!pages.length && fresh) {
    delete payload.Freshness;
    response = await run();
    if (response.Error) throw new Error("元宝搜索调用失败，请稍后重试");
    pages = parsePages(response);
  }
  return pages;
}

export function parsePages(response) {
  return list(response.Pages).flatMap(raw => {
    let page;
    try { page = typeof raw === "string" ? JSON.parse(raw) : raw; } catch { return []; }
    if (!page || !clean(page.title, 500)) return [];
    let url;
    try { url = new URL(page.url); } catch { return []; }
    if (!["http:", "https:"].includes(url.protocol)) return [];
    const date = String(page.date || "").replaceAll("/", "-").slice(0, 10);
    const dateValid = /^\d{4}-\d{2}-\d{2}$/.test(date) && !Number.isNaN(Date.parse(date)) && new Date(date).toISOString().slice(0, 10) === date;
    return [{title: clean(page.title, 500), url: page.url, snippet: clean(page.passage || page.content, 500),
      source_domain: clean(page.site, 200) || url.hostname.replace(/^www\./, ""), date: dateValid ? date : null,
      authority: Number.isInteger(page.authority_level) ? page.authority_level : null,
      api_score: typeof page.score === "number" ? page.score : null}];
  });
}

async function chatJSON(env, system, user, maxTokens) {
  const base = (env.LLM_BASE_URL || "https://api.deepseek.com").replace(/\/+$/, "");
  if (new URL(base).protocol !== "https:") throw new Error("模型接口必须使用 HTTPS");
  const response = await postJSON(`${base}/chat/completions`, {Authorization: `Bearer ${env.LLM_API_KEY || env.DEEPSEEK_API_KEY}`}, {
    model: env.LLM_MODEL || "deepseek-flash", messages: [{role: "system", content: system}, {role: "user", content: user}],
    max_tokens: maxTokens, stream: false, temperature: 0, thinking: {type: "disabled"}, response_format: {type: "json_object"},
  });
  const text = response.choices?.[0]?.message?.content || "";
  const start = text.indexOf("{"), end = text.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("模型没有返回有效 JSON");
  const data = JSON.parse(text.slice(start, end + 1));
  if (!data || Array.isArray(data) || typeof data !== "object") throw new Error("模型没有返回有效 JSON");
  return data;
}

async function decompose(env, question) {
  const fallback = {claim: question, sub_questions: [{question, query: clean(question, 80), fresh: false}], used_llm: false};
  if (!modelReady(env)) return fallback;
  let data;
  try { data = await chatJSON(env, prompts._DECOMPOSE_SYSTEM, `待核实内容：${question}`, 800); }
  catch (error) { reportUpstream("decompose", error, env); return fallback; }
  if (data.refuse === true) throw new Error(`这个问题不在侦探的查证范围内：${clean(data.refuse_reason || "涉及时政或个人隐私", 150)}`);
  const seen = new Set();
  const subs = list(data.sub_questions).flatMap(raw => {
    if (!raw || typeof raw !== "object") return [];
    const query = clean(raw.query || raw.question, 80).replace(/\s+/g, " ");
    if (!query || seen.has(query)) return [];
    seen.add(query);
    return [{question: clean(raw.question || query, 120), query, fresh: raw.fresh === true}];
  }).slice(0, 4);
  return subs.length ? {claim: clean(data.claim || question, 200), sub_questions: subs, used_llm: true} : fallback;
}

export function validateVerdict(raw, evidence) {
  const byId = new Map(evidence.map(e => [e.id, e]));
  const notes = [];
  let verdict = VERDICTS.includes(raw.verdict) ? raw.verdict : "说不准";
  const sourceIds = ids => [...new Set(list(ids).filter(id => typeof id === "string" && byId.has(id)))];
  const sources = ids => ids.map(id => {const e = byId.get(id); return {id, title: e.title, url: e.url, site: e.source_domain, date: e.date};});
  const claims = list(raw.claims).flatMap(c => {
    if (!c || !clean(c.text, 300)) return [];
    const ids = sourceIds(c.evidence);
    if (ids.length !== list(c.evidence).length) notes.push("已丢弃不存在的证据编号");
    return [{text: clean(c.text, 300), evidence: ids, sources: sources(ids)}];
  });
  if (["真", "假"].includes(verdict) && (!claims.length || claims.some(c => !c.evidence.length))) {
    verdict = "没查到可靠来源";
    notes.push("关键说法缺少有效证据，不给出真假判断");
  }
  if (!evidence.length) verdict = "没查到可靠来源";
  const candidates = list(raw.candidates).flatMap(c => {
    if (!c || !clean(c.name, 60)) return [];
    const ids = sourceIds(c.evidence);
    return ids.length ? [{name: clean(c.name, 60), why: clean(c.why, 200), evidence: ids, sources: sources(ids)}] : [];
  }).slice(0, 5);
  const conflicts = list(raw.conflicts).filter(c => c && clean(c.summary, 300))
    .map(c => ({summary: clean(c.summary, 300), basis: clean(c.basis, 300)}));
  return {verdict, reasoning: clean(raw.reasoning, 600), claims, conflicts, candidates, notes};
}

export async function investigate(env, question, progress) {
  await progress("decompose", "正在拆解问题…");
  const plan = await decompose(env, question);
  await progress("search", `正在用元宝搜索查 ${plan.sub_questions.length} 个子问题…`);
  const calls = {count: 0};
  const outcomes = await Promise.allSettled(plan.sub_questions.map(s => searchPro(env, s.query, s.fresh, calls)));
  for (const outcome of outcomes) if (outcome.status === "rejected") reportUpstream("search", outcome.reason, env);
  if (outcomes.every(o => o.status === "rejected")) throw new Error("元宝搜索暂时不可用，请检查服务配置或稍后重试");
  const merged = new Map();
  outcomes.forEach((o, i) => {
    const items = o.status === "fulfilled" ? o.value : [];
    plan.sub_questions[i].result_count = items.length;
    for (const item of items) {
      if (merged.has(item.url)) merged.get(item.url).queries.push(plan.sub_questions[i].query);
      else merged.set(item.url, {...item, queries: [plan.sub_questions[i].query]});
    }
  });
  const evidence = [...merged.values()].sort((a, b) =>
    (b.authority || 0) - (a.authority || 0) || b.queries.length - a.queries.length ||
    Math.round((b.api_score || 0) * 1000) - Math.round((a.api_score || 0) * 1000) ||
    (b.date || "").localeCompare(a.date || "") || a.url.localeCompare(b.url)
  ).slice(0, 12).map((e, i) => ({...e, id: `E${i + 1}`}));
  await progress("judge", "正在对照证据下结论…");
  let raw = {verdict: "没查到可靠来源", reasoning: "元宝搜索没有返回能回答这个问题的内容，所以不给出判断。"};
  if (evidence.length) {
    raw = {verdict: "说不准", reasoning: "未配置大模型，只列出查到的证据，请自行判断。"};
    if (modelReady(env)) {
      const block = evidence.map(e => JSON.stringify({id: e.id, title: e.title, site: e.source_domain,
        date: e.date || "未知", authority: e.authority, passage: e.snippet.slice(0, 400)})).join("\n");
      try {
        raw = await chatJSON(env, prompts._VERDICT_SYSTEM,
          `要核实的说法：${plan.claim}\n原始问题：${question}\n<evidence>\n${block}\n</evidence>`, 1500);
      } catch (error) { reportUpstream("judge", error, env); raw.reasoning = "大模型暂时不可用，只列出查到的证据，请自行判断。"; }
    }
  }
  const verdict = validateVerdict(raw, evidence);
  return {question, claim: plan.claim, ...verdict, sub_questions: plan.sub_questions,
    evidence: evidence.map(e => ({id: e.id, title: e.title, url: e.url, site: e.source_domain,
      date: e.date, authority: e.authority, snippet: e.snippet.slice(0, 200)})),
    folk: [], search_calls: calls.count, used_llm: plan.used_llm && modelReady(env),
    checked_at: new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 16).replace("T", " "),
    from_cache: false, cache_age_minutes: 0};
}

// A single coordinator enforces the daily budget globally, rather than per edge.
export class DetectiveJobs {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; }

  async fetch(request) {
    const path = new URL(request.url).pathname;
    const storage = this.ctx.storage;
    if (request.method === "GET" && /^\/api\/status\/[0-9a-f]{16}$/.test(path)) {
      const job = await storage.get("job:" + path.split("/").pop());
      if (!job || Date.now() - job.created > TTL) return json({error: "任务不存在或已过期"}, 404);
      return json({state: job.state, stage: job.stage, message: job.message, result: job.result || null, error: job.error || null});
    }
    if (request.method !== "POST" || path !== "/api/check") return json({error: "not found"}, 404);
    let body;
    try { body = await request.json(); } catch { return json({error: "请求内容无效"}, 400); }
    const question = typeof body?.question === "string" ? body.question.replace(/\s+/g, " ").trim() : "";
    if (!question || [...question].length > 200) return json({error: "请输入 1 到 200 字的查证内容"}, 400);
    if (!searchReady(this.env)) return json({error: CONFIG_ERROR}, 503);
    const now = Date.now();
    const clientKey = "client:" + await digest(request.headers.get("CF-Connecting-IP") || "unknown");
    const cacheKey = "cache:" + await digest(question.toLowerCase().replace(/[\p{P}\p{S}\s_]+/gu, ""));
    const id = crypto.randomUUID().replaceAll("-", "").slice(0, 16);
    const outcome = await storage.transaction(async txn => {
      const day = await txn.get("quota") || {day: dateKey(), count: 0};
      if (day.day !== dateKey()) { day.day = dateKey(); day.count = 0; }
      const hits = ((await txn.get(clientKey)) || []).filter(t => now - t < 60000);
      if (hits.length >= Number(this.env.PER_MINUTE || 6)) return {error: "查得太快了，请稍等一分钟"};
      if (day.count >= Number(this.env.PER_DAY || 300)) return {error: "今天的查询额度已用完，明天再来"};
      hits.push(now); day.count++;
      await txn.put({[clientKey]: hits, quota: day});
      const cached = body.refresh === true ? null : await txn.get(cacheKey);
      const valid = cached && now - cached.created < CACHE_TTL;
      await txn.put("job:" + id, {created: now, question, cacheKey, attempts: 0,
        state: valid ? "done" : "running", stage: valid ? "done" : "queued", message: valid ? "使用缓存结果" : "排队中…",
        ...(valid ? {result: {...cached.result, from_cache: true, cache_age_minutes: Math.round((now - cached.created) / 60000)}} : {})});
      await txn.setAlarm(now + 100);
      return {job: id};
    });
    return json(outcome, outcome.error ? 429 : 202);
  }

  async alarm() {
    const storage = this.ctx.storage;
    const jobs = await storage.list({prefix: "job:"});
    let selected;
    for (const [key, job] of jobs) {
      if (Date.now() - job.created > TTL) await storage.delete(key);
      else if (job.state === "running" && !selected) selected = [key, job];
    }
    if (selected) {
      const [key, job] = selected;
      job.attempts++;
      await storage.put(key, job);
      try {
        if (job.attempts > 2) throw new Error("查证任务中断，请重新提交");
        const result = await investigate(this.env, job.question, async (stage, message) => {
          job.stage = stage; job.message = message; await storage.put(key, job);
        });
        await storage.put({[key]: {...job, state: "done", stage: "done", message: "完成", result},
          [job.cacheKey]: {created: Date.now(), result}});
      } catch (error) {
        const message = error?.name === "TimeoutError" ? "上游服务响应超时，请稍后重试" :
          /^(这个问题不在|查证任务中断|元宝搜索暂时)/.test(error?.message || "") ? error.message : "查证过程出错了，请稍后再试";
        await storage.put(key, {...job, state: "error", error: message});
      }
    }
    // Re-read because requests can enqueue jobs while upstream requests are running.
    const current = await storage.list({prefix: "job:"});
    const pending = [...current.values()].some(j => j.state === "running" && Date.now() - j.created <= TTL);
    // Periodic cleanup also removes old IP hashes, cached content and completed jobs.
    for (const [key, cached] of await storage.list({prefix: "cache:"})) {
      if (Date.now() - cached.created > CACHE_TTL) await storage.delete(key);
    }
    for (const [key, hits] of await storage.list({prefix: "client:"})) {
      if (hits.every(t => Date.now() - t >= 60000)) await storage.delete(key);
    }
    if (pending || current.size) await storage.setAlarm(Date.now() + (pending ? 100 : TTL));
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/health" && ["GET", "HEAD"].includes(request.method)) {
      return json({ok: true, search_configured: searchReady(env), model_configured: modelReady(env)});
    }
    if (url.pathname.startsWith("/api/")) {
      if (request.method === "POST") {
        const origin = request.headers.get("Origin");
        if (origin && origin !== url.origin) return json({error: "不允许跨站请求"}, 403);
        if (!request.headers.get("Content-Type")?.toLowerCase().startsWith("application/json")) return json({error: "请使用 JSON 请求"}, 415);
        if (Number(request.headers.get("Content-Length") || 0) > MAX_BODY) return json({error: "请求内容过大"}, 413);
        const reader = request.body?.getReader();
        if (!reader) return json({error: "请求内容无效"}, 400);
        const chunks = []; let size = 0;
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          size += value.length;
          if (size > MAX_BODY) { await reader.cancel(); return json({error: "请求内容过大"}, 413); }
          chunks.push(value);
        }
        const raw = new Uint8Array(size); let offset = 0;
        for (const chunk of chunks) {raw.set(chunk, offset); offset += chunk.length;}
        request = new Request(request.url, {method: request.method, headers: request.headers, body: raw});
      }
      const stub = env.JOBS.get(env.JOBS.idFromName("detective-v1"));
      return stub.fetch(request);
    }
    if (!["GET", "HEAD"].includes(request.method)) return json({error: "method not allowed"}, 405);
    if (url.pathname === "/") url.pathname = "/index.html";
    const response = await env.ASSETS.fetch(new Request(url, request));
    const headers = new Headers(response.headers);
    for (const [key, value] of Object.entries(HEADERS)) headers.set(key, value);
    return new Response(response.body, {status: response.status, headers});
  },
};
