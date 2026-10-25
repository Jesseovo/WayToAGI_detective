# Cloudflare deployment

Live domain: <https://detective.ovoxin.top/>

The Worker serves the existing `scripts/lib/detective_page.html` and
`detective_page.js`. Build-time extraction keeps the model prompts identical
to `scripts/lib/detective.py`; `worker.mjs` adapts its search, citation checking
and result schema to the edge runtime. The Python CLI and local server still
work as before.

```powershell
python scripts/build_cloudflare.py
node --test tests/test_cloudflare.mjs
npx --yes wrangler@4.152.0 deploy --config scripts/cloudflare/wrangler.jsonc
```

Required server-side secrets (never put these in frontend assets or Git):

- `TENCENTCLOUD_SECRET_ID` and `TENCENTCLOUD_SECRET_KEY`: Tencent SearchPro.
- `DEEPSEEK_API_KEY` or `LLM_API_KEY`: model API, needed for generated verdicts.
- Optional `TENCENTCLOUD_TOKEN`, `LLM_BASE_URL`, `LLM_MODEL` overrides.

Set each with `npx --yes wrangler@4.152.0 secret put KEY --config
scripts/cloudflare/wrangler.jsonc`, or use `wrangler secret bulk` with a local
ignored JSON file. Set a custom model name when using a different provider.
Without search secrets, `/api/check` returns an explicit 503 instead of a
fabricated result. Without a model key, it returns the retrieved evidence and
an inconclusive verdict, matching the Python fallback.

`/api/health` reports deployment health plus `search_configured` and
`model_configured`, without exposing credentials. After configuration, test
one real question and verify that all cited links came from search results.

One SQLite Durable Object coordinates asynchronous jobs and enforces the
repository's limits globally: six submissions per IP per minute and 300 per
day. Job state expires after 30 minutes; normalized question results are
cached for six hours. IPs are stored only as hashes and removed on cleanup.
Polling does not create another model/search request. Alarms keep jobs alive
after the submitting HTTP request ends. Unexpected failures are sanitized.

The edge adapter runs the core evidence-based investigation. The optional
Python social-platform crawlers (`folk`) are not deployed: they depend on
platform-specific sessions and local/browser adapters. Their absence does
not manufacture social results or replace search evidence with model memory.

Deployments are snapshots made by Wrangler; GitHub pushes do not auto-deploy.
To update the site, rerun the build, checks and deployment command above.
