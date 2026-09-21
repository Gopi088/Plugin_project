"""Backend HTTP API (stdlib only, no framework needed).

    venv/bin/python backend/server.py [--port 8000] [--db backend/data/store.db]

Endpoints (the extension never touches pipeline internals):
    POST /api/documents            submit resume (JSON: filename, content_b64 | text, source?)
    GET  /api/documents/{id}/status
    GET  /api/documents/{id}/timeline
    GET  /api/documents/{id}/evidence?gap_id=.. | ?event_id=..
    GET  /api/documents/{id}/stages
    POST /api/documents/{id}/feedback   {dismissed_gap_ids[], overrides[], notes?}
    GET  /api/quality                  measured accuracy (eval/latest.json)
    GET  /health
"""

import argparse
import base64
import json
import os
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import docstore as DB
from backend.pipeline_context import PipelineContext
from backend.pipeline import runner
from backend import ml_assist

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "store.db")
EVAL_PATH = os.environ.get(
    "RT_EVAL_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "eval", "latest.json"))


def _process(filename, raw_bytes, raw_text, source):
    ctx = PipelineContext(DB.new_doc_id(), filename or "resume",
                          raw_text=raw_text or "", raw_bytes=raw_bytes or b"",
                          source=source or "upload",
                          model_versions={"model_timeline": ml_assist.version()})
    runner.run(ctx)
    overall = ctx.recruiter_output.get("status", "PARTIAL") if ctx.recruiter_output else "FAILED"
    cx = DB.connect(DB_PATH)
    try:
        DB.save_result(cx, ctx, overall)
    finally:
        cx.close()
    return ctx.doc_id, overall


class Handler(BaseHTTPRequestHandler):
    server_version = "ResumeTimeline/1.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        try:
            if parts == ["health"]:
                return self._json(200, {"ok": True,
                                        "model_versions": {"model_timeline": ml_assist.version()}})
            if parts == ["api", "quality"]:
                try:
                    with open(EVAL_PATH, encoding="utf-8") as fh:
                        rep = json.load(fh)
                    rep["model_versions"] = {"model_timeline": ml_assist.version()}
                    return self._json(200, rep)
                except FileNotFoundError:
                    return self._json(404, {"error": "no evaluation yet; run venv/bin/python eval/metrics.py"})
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "documents":
                doc_id, action = parts[2], (parts[3] if len(parts) > 3 else "")
                cx = DB.connect(DB_PATH)
                try:
                    if action == "status":
                        r = DB.get_status(cx, doc_id)
                    elif action == "timeline":
                        r = DB.get_timeline(cx, doc_id)
                    elif action == "stages":
                        r = DB.get_stages(cx, doc_id)
                    elif action == "evidence":
                        q = parse_qs(u.query)
                        r = DB.get_evidence(cx, doc_id,
                                            gap_id=(q.get("gap_id", [None])[0]),
                                            event_id=(q.get("event_id", [None])[0]))
                    else:
                        return self._json(404, {"error": "unknown endpoint"})
                finally:
                    cx.close()
                if r is None:
                    return self._json(404, {"error": "document not found"})
                return self._json(200, r)
            return self._json(404, {"error": "unknown endpoint"})
        except Exception as exc:
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            try:
                payload = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except Exception:
                return self._json(400, {"error": "malformed JSON body"})
            if parts == ["api", "documents"]:
                filename = payload.get("filename", "resume")
                raw_bytes, raw_text = b"", payload.get("text", "")
                if payload.get("content_b64"):
                    try:
                        raw_bytes = base64.b64decode(payload["content_b64"], validate=True)
                    except Exception:
                        return self._json(400, {"error": "invalid content_b64"})
                elif payload.get("source_url"):
                    u = urlparse(payload["source_url"])
                    if u.scheme not in ("http", "https"):
                        return self._json(400, {"error": "source_url must use HTTP or HTTPS"})
                    host = u.hostname or ""
                    if not host or host.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                        return self._json(400, {"error": "forbidden host in source_url"})
                    import socket
                    import ipaddress
                    try:
                        resolved = socket.getaddrinfo(host, None)
                        for item in resolved:
                            ip = ipaddress.ip_address(item[4][0])
                            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                                return self._json(400, {"error": "forbidden internal network host"})
                    except socket.gaierror:
                        return self._json(400, {"error": "invalid host in source_url"})
                    try:
                        req = urllib.request.Request(
                            payload["source_url"],
                            headers={"User-Agent": "ResumeTimeline/1.0"})
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            raw_bytes = resp.read(25_000_000)
                        filename = unquote(urlparse(payload["source_url"]).path.rsplit("/", 1)[-1]) or filename
                    except Exception as exc:
                        return self._json(422, {"error": f"fetch failed: {exc}"})
                if not raw_bytes and not (raw_text or "").strip():
                    return self._json(400, {"error": "provide content_b64, text, or source_url"})
                doc_id, status = _process(filename, raw_bytes, raw_text,
                                          payload.get("source", "upload"))
                return self._json(200, {"doc_id": doc_id, "status": status})
            if (len(parts) == 4 and parts[0] == "api" and parts[1] == "documents"
                    and parts[3] == "feedback"):
                cx = DB.connect(DB_PATH)
                try:
                    if not DB.get_status(cx, parts[2]):
                        return self._json(404, {"error": "document not found"})
                    DB.save_feedback(cx, parts[2], payload.get("dismissed_gap_ids"),
                                     payload.get("overrides"), payload.get("notes"))
                finally:
                    cx.close()
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "unknown endpoint"})
        except Exception as exc:
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, fmt, *args):  # quieter logs -> stderr, one line
        sys.stderr.write("api %s\n" % (fmt % args))


def main():
    global DB_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--db", default=DB_PATH)
    args = ap.parse_args()
    DB_PATH = args.db
    DB.init_db(DB_PATH)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Resume Timeline API on http://{args.host}:{args.port} (db={DB_PATH})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
