#!/usr/bin/env python3
"""Probe a Fusion360 MCP server endpoint (Streamable HTTP / JSON-RPC 2.0).

Run this before starting a modeling session to confirm the MCP server is
online, and optionally list the tools it exposes.

Examples:
    python check_mcp_server.py                      # probe default endpoint /mcp
    python check_mcp_server.py --tools --detail     # list tools with params
    python check_mcp_server.py --tools --json       # full tool schemas as JSON
    python check_mcp_server.py --endpoint http://127.0.0.1:27182/mcp

Exit codes:
    0 - server reachable and responded to MCP initialize
    1 - server unreachable or protocol handshake failed
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "http://127.0.0.1:27182"
# The Fusion360 MCP adapter serves MCP on /mcp; other paths are fallbacks.
# If --endpoint already ends with /mcp, no extra path is appended.
DEFAULT_PATHS = ["/mcp", "", "/mcp/"]
PROTOCOL_VERSION = "2025-03-26"
CLIENT_INFO = {"name": "fusion360-mcp-cad-skill-checker", "version": "1.0.0"}


if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _post(url, payload, session_id=None, timeout=5.0):
    """POST a JSON-RPC payload, return (status, headers_dict, body_text)."""
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
        return response.status, {k.lower(): v for k, v in response.headers.items()}, body


def _parse_messages(content_type, body):
    """Extract JSON-RPC messages from a plain JSON or SSE response body."""
    messages = []
    if not body or not body.strip():
        return messages
    if "text/event-stream" in (content_type or ""):
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[5:].strip()
                try:
                    messages.append(json.loads(chunk))
                except json.JSONDecodeError:
                    continue
    else:
        try:
            messages.append(json.loads(body))
        except json.JSONDecodeError:
            return messages
    return messages


def _initialize_payload(request_id=1):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        },
    }


def probe(endpoint, path, timeout):
    """Attempt an MCP initialize handshake on one candidate path."""
    url = endpoint.rstrip("/") + path
    result = {"url": url, "status": None, "ok": False, "session": None, "server": None, "detail": ""}
    try:
        status, headers, body = _post(url, _initialize_payload(), timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        result["status"] = exc.code
        result["detail"] = "HTTP {} from {}; body: {}".format(
            exc.code, url, body[:300] if body else "<empty>"
        )
        return result
    except urllib.error.URLError as exc:
        result["detail"] = "connection failed: {}".format(exc.reason)
        return result
    except Exception as exc:  # socket timeout, malformed URL, etc.
        result["detail"] = "{}: {}".format(type(exc).__name__, exc)
        return result

    result["status"] = status
    result["session"] = headers.get("mcp-session-id")
    messages = _parse_messages(headers.get("content-type", ""), body)
    for message in messages:
        if isinstance(message, dict) and message.get("id") == 1:
            if "result" in message:
                result["ok"] = True
                info = message.get("result", {}).get("serverInfo", {}) or {}
                result["server"] = "{} {}".format(info.get("name", "?"), info.get("version", "")).strip()
                result["detail"] = "initialize OK"
                return result
            if "error" in message:
                result["detail"] = "JSON-RPC error: {}".format(json.dumps(message["error"])[:300])
                return result
    result["detail"] = "no JSON-RPC initialize response; body: {}".format(body[:300] if body else "<empty>")
    return result


def list_tools(endpoint, path, session_id, timeout):
    """Request tools/list after a successful handshake."""
    url = endpoint.rstrip("/") + path
    try:
        _post(
            url,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            session_id=session_id,
            timeout=timeout,
        )
    except Exception:
        pass

    try:
        _, headers, body = _post(
            url,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_id=session_id,
            timeout=timeout,
        )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return [], "HTTP {}: {}".format(exc.code, body[:200])
    except Exception as exc:
        return [], "{}: {}".format(type(exc).__name__, exc)

    for message in _parse_messages(headers.get("content-type", ""), body):
        if isinstance(message, dict) and message.get("id") == 2:
            tools = message.get("result", {}).get("tools", [])
            return [tool for tool in tools if isinstance(tool, dict)], ""
    return [], "no tools/list response; body: {}".format(body[:200] if body else "<empty>")


def param_summary(tool):
    """Return 'name:type' entries ('*' marks required) from a tool inputSchema."""
    schema = tool.get("inputSchema") or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    entries = []
    for name, spec in properties.items():
        kind = ""
        if isinstance(spec, dict):
            kind = spec.get("type", "")
            if isinstance(kind, list):
                kind = "/".join(str(item) for item in kind)
        marker = "*" if name in required else ""
        entries.append("{}{}{}".format(name, marker, ":{}".format(kind) if kind else ""))
    return entries


def main():
    parser = argparse.ArgumentParser(
        description="Probe a Fusion360 MCP server endpoint and optionally list its tools."
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="base URL, default %s" % DEFAULT_ENDPOINT)
    parser.add_argument("--path", default=None, help="MCP path; default tries '', '/mcp', '/mcp/'")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-request timeout in seconds")
    parser.add_argument("--tools", action="store_true", help="list tools after a successful handshake")
    parser.add_argument("--detail", action="store_true", help="with --tools, also print each tool description and params")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON (includes full tool schemas)")
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    if args.path:
        candidates = [args.path]
    elif endpoint.endswith("/mcp"):
        candidates = [""]  # endpoint already points at the MCP path
    else:
        candidates = DEFAULT_PATHS
    report = {
        "endpoint": args.endpoint,
        "reachable": False,
        "endpoint_url": None,
        "server": None,
        "session": None,
        "tools": [],
        "attempts": [],
        "tools_error": "",
    }

    successful_path = ""
    for path in candidates:
        attempt = probe(endpoint, path, args.timeout)
        report["attempts"].append(attempt)
        if attempt["ok"]:
            report["reachable"] = True
            report["endpoint_url"] = attempt["url"]
            report["server"] = attempt["server"]
            report["session"] = attempt["session"]
            successful_path = path
            break
        # A transport-level failure (no HTTP status) affects every path on the
        # same host:port, so stop early instead of waiting for more timeouts.
        if attempt["status"] is None:
            break

    if report["reachable"] and args.tools:
        # Reuse the path that answered the handshake instead of assuming one.
        tools, error = list_tools(endpoint, successful_path, report["session"], args.timeout)
        report["tools"] = tools
        report["tools_error"] = error

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("Fusion360 MCP server check")
        print("  endpoint : %s" % args.endpoint)
        if report["reachable"]:
            print("  status   : ONLINE")
            print("  url      : %s" % report["endpoint_url"])
            if report["server"]:
                print("  server   : %s" % report["server"])
            if args.tools:
                if report["tools"]:
                    print("  tools    : %d available" % len(report["tools"]))
                    for tool in report["tools"]:
                        print("             - %s" % tool.get("name", "?"))
                        if args.detail:
                            description = " ".join((tool.get("description") or "").split())
                            if description:
                                print("               %s" % description[:240])
                            params = param_summary(tool)
                            print("               params: %s" % (", ".join(params) if params else "<none>"))
                else:
                    print("  tools    : unavailable (%s)" % (report["tools_error"] or "unknown reason"))
        else:
            print("  status   : OFFLINE / handshake failed")
            for attempt in report["attempts"]:
                print("  attempt  : %s" % attempt["url"])
                print("             %s" % attempt["detail"])
            print("  hint     : start Fusion 360, load the MCP add-in, then confirm the endpoint/port.")

    sys.exit(0 if report["reachable"] else 1)


if __name__ == "__main__":
    main()
