#!/usr/bin/env python3
"""Optional Streamable HTTP diagnostic, not a modeling prerequisite.

Python 3.10+, standard library only. POST JSON or SSE responses; tools/list
pagination. No stdio, legacy two-endpoint SSE, OAuth, or server-initiated RPC.
Exit 0: requested initialization/discovery succeeded; 1: request failed;
2: invalid CLI configuration. This does not certify modeling capabilities.
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENDPOINT = "http://127.0.0.1:27182/mcp"
PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_VERSIONS = {"2025-03-26", "2025-06-18", "2025-11-25"}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class ProtocolError(Exception):
    pass


def _parse_messages(content_type, body):
    """Parse complete JSON or SSE events; multi-line data belongs to one event."""
    if "text/event-stream" not in content_type.lower():
        return [json.loads(body)] if body.strip() else []
    messages, data = [], []
    for line in body.splitlines() + [""]:
        if not line:
            if data:
                messages.append(json.loads("\n".join(data)))
                data = []
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    return messages


def _result(message, request_id):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or message.get("id") != request_id:
        raise ProtocolError("invalid or mismatched JSON-RPC response")
    if "error" in message:
        error = message["error"]
        if isinstance(error, dict):
            raise ProtocolError("JSON-RPC %s: %s" % (error.get("code"), error.get("message")))
        raise ProtocolError("malformed JSON-RPC error")
    if not isinstance(message.get("result"), dict):
        raise ProtocolError("missing object result in JSON-RPC response")
    return message["result"]


class Client:
    def __init__(self, url, timeout=5.0, token=None):
        self.url, self.timeout, self.token = url, timeout, token
        self.session, self.version = None, None
        self.next_id = 0

    def post(self, method, params=None, notification=False):
        self.next_id += 1
        request_id = self.next_id
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            payload["id"] = request_id
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.url, json.dumps(payload).encode("utf-8"), headers, method="POST")
        deadline = time.monotonic() + self.timeout
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if method == "initialize":
                    self.session = response.headers.get("Mcp-Session-Id")
                if notification:
                    if response.status != 202:
                        raise ProtocolError("notification expected HTTP 202, got %s" % response.status)
                    return None
                content_type = response.headers.get("Content-Type", "").lower()
                if "text/event-stream" in content_type:
                    data, total = [], 0
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("SSE response deadline exceeded")
                        # urllib has no public setter for the remaining read budget.
                        # HTTPResponse uses this socket on CPython; initial socket
                        # timeout remains a bounded fallback on other runtimes.
                        sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
                        if sock is not None:
                            sock.settimeout(remaining)
                        line = response.readline(MAX_RESPONSE_BYTES - total + 1)
                        total += len(line)
                        if total > MAX_RESPONSE_BYTES:
                            raise ProtocolError("response exceeds 8 MiB limit")
                        if not line:
                            raise ProtocolError("SSE ended before matching response")
                        line = line.decode("utf-8").rstrip("\r\n")
                        if line.startswith("data:"):
                            value = line[5:]
                            data.append(value[1:] if value.startswith(" ") else value)
                        elif not line and data:
                            message = json.loads("\n".join(data))
                            data = []
                            if not isinstance(message, dict):
                                raise ProtocolError("SSE event must contain a JSON-RPC object")
                            if "method" in message and "id" in message:
                                raise ProtocolError("server-initiated RPC is unsupported by this diagnostic")
                            if message.get("id") == request_id:
                                return _result(message, request_id)
                if "application/json" not in content_type:
                    raise ProtocolError("expected application/json or text/event-stream")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProtocolError("response exceeds 8 MiB limit")
                return _result(json.loads(body), request_id)
        except urllib.error.HTTPError as exc:
            # Do not echo response bodies, request headers or session identifiers.
            raise ProtocolError("HTTP %s" % exc.code) from exc
        except urllib.error.URLError as exc:
            raise ProtocolError("connection failed: %s" % exc.reason) from exc
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError("invalid JSON/UTF-8 response") from exc

    def initialize(self):
        result = self.post("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "fusion360-skill-checker", "version": "2.0.0"}})
        version = result.get("protocolVersion")
        if not isinstance(version, str) or version not in SUPPORTED_VERSIONS:
            raise ProtocolError("unsupported negotiated protocol version: %r" % version)
        if not isinstance(result.get("serverInfo"), dict) or not isinstance(result.get("capabilities"), dict):
            raise ProtocolError("initialize missing serverInfo or capabilities object")
        self.version = version
        self.post("notifications/initialized", notification=True)
        return result

    def list_tools(self):
        tools, cursors, cursor = [], set(), None
        for _ in range(100):
            result = self.post("tools/list", {"cursor": cursor} if cursor is not None else {})
            page = result.get("tools")
            if not isinstance(page, list):
                raise ProtocolError("tools/list missing tools array")
            for tool in page:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not isinstance(tool.get("inputSchema"), dict):
                    raise ProtocolError("malformed tool definition")
            tools.extend(page)
            cursor = result.get("nextCursor")
            if cursor is None:
                return tools
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ProtocolError("invalid or repeated tools/list cursor")
            cursors.add(cursor)
        raise ProtocolError("tools/list exceeded 100-page limit")


def check(endpoint, timeout=5.0, include_tools=False, token=None):
    client = Client(endpoint, timeout, token)
    report = {"endpoint_url": endpoint, "initialized": False, "protocol_version": None,
              "server": None, "tools_discovered": None, "tools": [], "error": "",
              "scope": "initialization-and-discovery-only"}
    try:
        init = client.initialize()
        report.update(initialized=True, protocol_version=client.version, server=init["serverInfo"])
        if include_tools:
            report["tools_discovered"] = False
            if "tools" not in init["capabilities"]:
                raise ProtocolError("server does not advertise tools capability")
            report["tools"] = client.list_tools()
            report["tools_discovered"] = True
    except (ProtocolError, OSError, ValueError, RecursionError) as exc:
        report["error"] = "%s: %s" % (type(exc).__name__, exc)
        for secret in (client.session, token):
            if secret:
                report["error"] = report["error"].replace(secret, "[redacted]")
    report["ok"] = report["initialized"] and (not include_tools or report["tools_discovered"] is True) and not report["error"]
    return report


def param_summary(tool):
    schema = tool.get("inputSchema") or {}
    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return []
    return ["%s%s" % (key, "*" if key in required else "") for key in properties]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="exact MCP URL; a bare origin uses /mcp")
    parser.add_argument("--path", help="explicit path overriding endpoint path")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-request timeout in seconds")
    parser.add_argument("--tools", action="store_true", help="require successful discovery of all tool pages")
    parser.add_argument("--detail", action="store_true", help="with --tools, show tool descriptions and parameter names")
    parser.add_argument("--json", action="store_true", help="emit machine-readable report")
    parser.add_argument("--token-env", help="optional environment variable containing a bearer token; never printed")
    args = parser.parse_args(argv)
    try:
        parsed = urllib.parse.urlsplit(args.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("endpoint must be an http(s) URL without credentials, query or fragment")
        _ = parsed.port
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if args.path and (not args.path.startswith("/") or "?" in args.path or "#" in args.path):
            raise ValueError("path must start with / and contain no query or fragment")
        endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, args.path or parsed.path or "/mcp", "", ""))
        token = os.environ.get(args.token_env) if args.token_env else None
        if args.token_env and not token:
            raise ValueError("token environment variable is unset or empty")
    except ValueError as exc:
        parser.error(str(exc))
    report = check(endpoint, args.timeout, args.tools, token)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Fusion MCP diagnostic: %s" % ("PASS" if report["ok"] else "FAIL"))
        print("  endpoint: %s" % endpoint)
        print("  initialized: %s; tools discovered: %s" % (report["initialized"], report["tools_discovered"]))
        if report["error"]:
            print("  error: %s" % report["error"])
        for tool in report["tools"]:
            print("  - %s" % tool["name"])
            if args.detail:
                print("    %s" % " ".join(str(tool.get("description", "")).split())[:240])
                print("    params: %s" % ", ".join(param_summary(tool)))
        print("  scope: connection/initialization/discovery; CAD operations are not verified")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
