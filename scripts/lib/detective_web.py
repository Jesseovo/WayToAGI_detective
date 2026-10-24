"""侦探网页：打开就能查。标准库 http.server，无第三方依赖。

安全说明：
- 默认只绑定 127.0.0.1。要让别人访问，需要显式传 --host，并自行放到有访问控制的环境里：
  接口本身没有登录鉴权，每次查询都会消耗元宝搜索额度和大模型费用。
- 内置限流（每个来源地址每分钟）和每日总量上限，防止额度被刷光。
- 页面用 textContent 渲染所有内容，链接只放行 http/https。
"""

import json
import re
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Tuple

from . import detective

ASSET_DIR = Path(__file__).parent
MAX_BODY_BYTES = 4096
JOB_TTL_SECONDS = 1800
MAX_JOBS = 200


class JobStore:
    """内存里的任务表，轮询取结果。"""

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        job_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._evict()
            self._jobs[job_id] = {
                "state": "running", "stage": "queued", "message": "排队中…",
                "result": None, "error": None, "created": time.time(),
            }
        return job_id

    def _evict(self) -> None:
        now = time.time()
        for key in [k for k, v in self._jobs.items() if now - v["created"] > JOB_TTL_SECONDS]:
            del self._jobs[key]
        while len(self._jobs) >= MAX_JOBS:
            oldest = min(self._jobs, key=lambda k: self._jobs[k]["created"])
            del self._jobs[oldest]

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


class RateLimiter:
    """滑动窗口限流 + 每日总量上限。"""

    def __init__(self, per_minute: int, per_day: int) -> None:
        self.per_minute = per_minute
        self.per_day = per_day
        self._hits: Dict[str, Deque[float]] = {}
        self._day = time.strftime("%Y-%m-%d")
        self._day_count = 0
        self._lock = threading.Lock()

    def allow(self, client: str) -> Tuple[bool, str]:
        now = time.time()
        with self._lock:
            today = time.strftime("%Y-%m-%d")
            if today != self._day:
                self._day, self._day_count = today, 0
            if self._day_count >= self.per_day:
                return False, "今天的查询额度已用完，明天再来"
            hits = self._hits.setdefault(client, deque())
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False, "查得太快了，请稍等一分钟"
            hits.append(now)
            self._day_count += 1
            return True, ""


def _json_bytes(data: Dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def make_handler(config: Dict[str, Any], jobs: JobStore, limiter: RateLimiter):
    index_html = (ASSET_DIR / "detective_page.html").read_bytes()
    app_js = (ASSET_DIR / "detective_page.js").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "Detective/1.0"

        def log_message(self, fmt, *args):  # 不记录查询内容
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
                "connect-src 'self'; base-uri 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: Dict[str, Any]) -> None:
            self._send(status, _json_bytes(data), "application/json; charset=utf-8")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, index_html, "text/html; charset=utf-8")
                return
            if path == "/app.js":
                self._send(200, app_js, "application/javascript; charset=utf-8")
                return
            if path == "/api/health":
                self._json(200, {"ok": True})
                return
            match = re.fullmatch(r"/api/status/([0-9a-f]{16})", path)
            if match:
                job = jobs.get(match.group(1))
                if not job:
                    self._json(404, {"error": "任务不存在或已过期"})
                    return
                self._json(200, {k: job[k] for k in ("state", "stage", "message", "result", "error")})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api/check":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY_BYTES:
                self._json(400, {"error": "请求内容无效"})
                return
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                question = str(body.get("question") or "")
            except (ValueError, UnicodeDecodeError, AttributeError):
                self._json(400, {"error": "请求内容无效"})
                return
            allowed, reason = limiter.allow(self.client_address[0])
            if not allowed:
                self._json(429, {"error": reason})
                return
            job_id = jobs.create()

            def progress(stage: str, message: str) -> None:
                jobs.update(job_id, stage=stage, message=message)

            def work() -> None:
                try:
                    result = detective.investigate(config, question, progress=progress)
                    jobs.update(job_id, state="done", stage="done", message="完成", result=result)
                except detective.DetectiveError as exc:
                    jobs.update(job_id, state="error", error=str(exc))
                except Exception as exc:  # 不把内部细节暴露给页面
                    sys.stderr.write(f"[侦探] 未预期的错误: {type(exc).__name__}: {exc}\n")
                    jobs.update(job_id, state="error", error="查证过程出错了，请稍后再试")

            threading.Thread(target=work, name=f"detective-{job_id}", daemon=True).start()
            self._json(202, {"job": job_id})

    return Handler


def serve(
    config: Dict[str, Any],
    host: str = "127.0.0.1",
    port: int = 8765,
    per_minute: int = 6,
    per_day: int = 300,
) -> None:
    jobs = JobStore()
    limiter = RateLimiter(per_minute, per_day)
    server = ThreadingHTTPServer((host, port), make_handler(config, jobs, limiter))
    server.daemon_threads = True
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    sys.stderr.write(f"侦探网页已启动: http://{shown}:{port}/  （Ctrl+C 退出）\n")
    if host not in ("127.0.0.1", "localhost"):
        sys.stderr.write("警告: 已对外监听。接口没有登录鉴权，请确认只有可信的人能访问。\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n已退出\n")
    finally:
        server.server_close()
