#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dota 2 分锅器 Web 后端（零第三方依赖，除 Pillow 用于分享卡片）。

启动:
    python3 server/app.py            # 默认 0.0.0.0:8000
    PORT=8080 python3 server/app.py

接口:
    GET  /                    前端页面
    GET  /api/health          健康检查
    GET  /api/analyze         ?match_id=9088291413&user_id=181585714  返回 JSON
    GET  /api/card            ?match_id=...&user_id=...              返回 PNG 分享卡片
    GET  /api/report          ?match_id=...&user_id=...              返回 Markdown 全文
"""

import json
import os
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
os.makedirs(os.path.join(ROOT, "cache"), exist_ok=True)
sys.path.insert(0, ROOT)

import dota_blame  # noqa: E402

try:
    from server import card  # noqa: E402
except ImportError:  # 直接 python3 server/app.py 运行时
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import card  # noqa: E402

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))

_CACHE = {}
_CACHE_LOCK = threading.Lock()

_STATUS_CACHE = {}
_STATUS_LOCK = threading.Lock()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
}


def _cached(match_id, user_id, refresh=False):
    key = (int(match_id), int(user_id) if user_id else 0)
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and not refresh and now - hit[0] < CACHE_TTL:
            return hit[1]
    payload = dota_blame.run(match_id, user_id, refresh=refresh)
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), payload)
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "dota-blame/1.0"

    # ---------- 基础响应 ----------
    def _send(self, code, body, content_type, extra_headers=None, cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False), MIME[".json"])

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    # ---------- 路由 ----------
    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._json(200, {"ok": True, "service": "dota-blame", "time": time.time()})
            elif path == "/api/analyze":
                self._api_analyze(qs)
            elif path == "/api/status":
                self._api_status(qs)
            elif path == "/api/card":
                self._api_card(qs)
            elif path == "/api/report":
                self._api_report(qs)
            elif path in ("/", "/index.html"):
                self._static("index.html")
            elif path.startswith("/static/"):
                self._static(path[len("/static/"):])
            else:
                self._send(404, "404 Not Found", MIME[".txt"])
        except dota_blame.MatchNotFound as e:
            self._json(404, {"ok": False, "error": str(e)})
        except ValueError as e:
            self._json(400, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"ok": False, "error": "服务器错误：%s" % e})

    # ---------- API ----------
    def _params(self, qs):
        try:
            match_id = int((qs.get("match_id") or [""])[0])
        except ValueError:
            raise ValueError("match_id 必须是数字，比如 9088291413")
        user_raw = (qs.get("user_id") or [""])[0].strip()
        user_id = None
        if user_raw:
            try:
                user_id = int(user_raw)
            except ValueError:
                raise ValueError("user_id 必须是数字（你的 account_id）")
        refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
        return match_id, user_id, refresh

    def _api_analyze(self, qs):
        match_id, user_id, refresh = self._params(qs)
        payload = _cached(match_id, user_id, refresh)
        self._json(200, payload)

    def _api_status(self, qs):
        try:
            match_id = int((qs.get("match_id") or [""])[0])
        except ValueError:
            raise ValueError("match_id 必须是数字，比如 9088291413")
        now = time.time()
        with _STATUS_LOCK:
            hit = _STATUS_CACHE.get(match_id)
            if hit and now - hit[0] < 10:
                self._json(200, hit[1])
                return
        result = dota_blame.check_parsed(match_id)
        with _STATUS_LOCK:
            _STATUS_CACHE[match_id] = (time.time(), result)
        self._json(200, result)

    def _api_card(self, qs):
        match_id, user_id, refresh = self._params(qs)
        payload = _cached(match_id, user_id, refresh)
        png = card.make_card(payload)
        self._send(200, png, MIME[".png"],
                   extra_headers={"Content-Disposition":
                                  'inline; filename="dota-blame-%s.png"' % match_id})

    def _api_report(self, qs):
        match_id, user_id, refresh = self._params(qs)
        payload = _cached(match_id, user_id, refresh)
        name = "dota-blame-%s.md" % match_id
        self._send(200, payload.get("report_md", ""), MIME[".md"],
                   extra_headers={"Content-Disposition": 'attachment; filename="%s"' % name})

    # ---------- 静态文件 ----------
    def _static(self, rel):
        safe = os.path.normpath(rel).lstrip(os.sep)
        full = os.path.normpath(os.path.join(WEB, safe))
        if not full.startswith(WEB + os.sep) and full != WEB:
            self._send(403, "403 Forbidden", MIME[".txt"])
            return
        if not os.path.isfile(full):
            self._send(404, "404 Not Found", MIME[".txt"])
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self._send(200, body, ctype, cache="public, max-age=300")


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    print("Dota2 分锅器: http://%s:%d" % ("127.0.0.1" if HOST == "0.0.0.0" else HOST, PORT))
    print("API: /api/analyze?match_id=9088291413&user_id=181585714")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        httpd.server_close()


if __name__ == "__main__":
    main()
