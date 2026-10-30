import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mcp_check", ROOT / "fusion360-mcp-cad/scripts/check_mcp_server.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)


@contextlib.contextmanager
def service(mode="json"):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((payload, dict(self.headers)))
            if payload["method"] == "notifications/initialized":
                self.send_response(500 if mode == "notification_error" else 202)
                self.end_headers()
                return
            is_init = payload["method"] == "initialize"
            if is_init:
                result = {"protocolVersion": "2099-01-01" if mode == "version_error" else "2025-06-18",
                          "serverInfo": {"name": "fixture", "version": "1"}, "capabilities": {"tools": {}}}
            else:
                cursor = payload.get("params", {}).get("cursor")
                result = {"tools": [{"name": "second" if cursor else "first", "description": "fixture \U0001f680", "inputSchema": {"type": "object"}}]}
                if mode in {"pages", "repeated_cursor", "page_error"} and (not cursor or mode == "repeated_cursor"):
                    result["nextCursor"] = "page2"
            message = {"jsonrpc": "2.0", "id": payload["id"], "result": result}
            if mode == "rpc_error" and not is_init or mode == "page_error" and not is_init and cursor:
                message.pop("result")
                message["error"] = {"code": -32603, "message": "fixture session-private token-private"}
            if mode == "malformed" and not is_init:
                message["result"]["tools"] = [{}]
            if mode == "wrong_id" and not is_init:
                message["id"] = 999
            self.send_response(200)
            self.send_header("Mcp-Session-Id", "session-private")
            self.send_header("Content-Type", "text/event-stream" if mode in {"sse", "timeout"} else "application/json")
            self.end_headers()
            if mode == "timeout" and not is_init:
                try:
                    for _ in range(20):
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        time.sleep(0.02)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            elif mode in {"sse", "timeout"}:
                text = json.dumps(message, indent=2)
                self.wfile.write((": comment\n" + "\n".join("data: " + line for line in text.splitlines()) + "\n\n").encode())
                self.wfile.flush()
            else:
                self.wfile.write(json.dumps(message).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield "http://127.0.0.1:%s/mcp" % server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class HttpTests(unittest.TestCase):
    def test_json_sse_and_paginated_discovery(self):
        for mode in ["json", "sse", "pages"]:
            with self.subTest(mode=mode), service(mode) as (url, requests):
                report = mcp.check(url, include_tools=True, token="token-private")
                self.assertTrue(report["ok"], report)
                self.assertEqual(len(report["tools"]), 2 if mode == "pages" else 1)
                for payload, headers in requests[1:]:
                    headers = {key.lower(): value for key, value in headers.items()}
                    self.assertEqual(headers["mcp-session-id"], "session-private")
                    self.assertEqual(headers["mcp-protocol-version"], "2025-06-18")
                self.assertNotIn("session-private", json.dumps(report))
                self.assertNotIn("token-private", json.dumps(report))

    def test_errors_fail_requested_discovery(self):
        for mode in ["rpc_error", "page_error", "repeated_cursor", "malformed", "wrong_id", "notification_error", "version_error"]:
            with self.subTest(mode=mode), service(mode) as (url, _):
                report = mcp.check(url, include_tools=True, token="token-private")
                self.assertFalse(report["ok"])
                self.assertTrue(report["error"])
                self.assertNotIn("session-private", report["error"])
                self.assertNotIn("token-private", report["error"])
                if mode == "rpc_error":
                    self.assertIn("-32603", report["error"])

    def test_discovery_error_has_failing_cli_exit_code(self):
        with service("rpc_error") as (url, _), contextlib.redirect_stdout(io.StringIO()) as output:
            code = mcp.main(["--endpoint", url, "--tools", "--json"])
        self.assertEqual(code, 1)
        report = json.loads(output.getvalue())
        self.assertTrue(report["initialized"])
        self.assertFalse(report["tools_discovered"])

    def test_initialize_only_still_sends_notification(self):
        with service() as (url, requests):
            report = mcp.check(url)
        self.assertTrue(report["ok"])
        self.assertIsNone(report["tools_discovered"])
        self.assertEqual([p["method"] for p, _ in requests], ["initialize", "notifications/initialized"])

    def test_keepalive_stream_has_deadline(self):
        with service("timeout") as (url, _):
            start = time.monotonic()
            report = mcp.check(url, timeout=0.15, include_tools=True)
            elapsed = time.monotonic() - start
        self.assertFalse(report["ok"])
        self.assertTrue(report["error"])
        self.assertLess(elapsed, 1.0)

    def test_complete_multiline_sse_parser(self):
        parsed = mcp._parse_messages("text/event-stream", ': comment\ndata: {"jsonrpc":"2.0",\ndata: "id":2,"result":{}}\n\n')
        self.assertEqual(parsed, [{"jsonrpc": "2.0", "id": 2, "result": {}}])

    def test_cli_emits_utf8_under_legacy_windows_encoding(self):
        with service() as (url, _):
            result = subprocess.run([sys.executable, str(ROOT / "fusion360-mcp-cad/scripts/check_mcp_server.py"),
                                     "--endpoint", url, "--tools", "--json"],
                                    env={**os.environ, "PYTHONIOENCODING": "gbk"}, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\U0001f680", json.loads(result.stdout.decode("utf-8"))["tools"][0]["description"])
