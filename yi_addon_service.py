#!/usr/bin/env python3
"""Versioned HTTP service for the future YI Home Add-on.

The service exposes only secret-safe backend/runtime state. When an env file is
provided, the per-camera lifecycle manager owns supervised native PPPP/TNP
runtimes and the capability probe supports bounded live reprobe operations.

Security defaults:
- bind to loopback by default;
- a non-loopback bind requires YI_ADDON_API_TOKEN;
- API responses never include YI UID/DID/password/token/license/InitString.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yi_tnp_oracle as oracle
from yi_addon_backend import YiAddonBackend
from yi_capability_cache import YiCapabilityCache
from yi_capability_probe_runtime import YiCapabilityProbe
from yi_runtime_lifecycle import YiRuntimeLifecycleManager, build_default_config

CAMERA_RE = re.compile(r"^/api/v1/cameras/([0-9a-f]{20})$")
STATUS_RE = re.compile(r"^/api/v1/cameras/([0-9a-f]{20})/status$")
START_RE = re.compile(r"^/api/v1/cameras/([0-9a-f]{20})/start$")
STOP_RE = re.compile(r"^/api/v1/cameras/([0-9a-f]{20})/stop$")
RESTART_RE = re.compile(r"^/api/v1/cameras/([0-9a-f]{20})/restart$")
REPROBE_RE = re.compile(r"^/api/v1/cameras/([0-9a-f]{20})/reprobe$")


def _is_loopback(bind: str) -> bool:
    return bind in {"127.0.0.1", "::1", "localhost"}


class YiAddonHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], backend: YiAddonBackend, api_token: str | None) -> None:
        super().__init__(address, YiAddonRequestHandler)
        self.backend = backend
        self.api_token = api_token


class YiAddonRequestHandler(BaseHTTPRequestHandler):
    server: YiAddonHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        # Avoid logging request paths/headers until a structured secret-safe
        # Add-on logger is introduced.
        return

    def _authorized(self) -> bool:
        token = self.server.api_token
        if token is None:
            return True
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        supplied = header[len(prefix):]
        return hmac.compare_digest(supplied, token)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(
            status,
            {
                "ok": False,
                "error": {"code": code, "message": message},
                "secrets_exposed": False,
            },
        )

    def _preflight(self) -> str | None:
        if not self._authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "unauthorized", "A valid Add-on API token is required.")
            return None
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._error(HTTPStatus.BAD_REQUEST, "query_not_supported", "Query strings are not supported by this API.")
            return None
        return parsed.path

    def do_GET(self) -> None:  # noqa: N802
        path = self._preflight()
        if path is None:
            return
        if path == "/api/v1/health":
            self._json(HTTPStatus.OK, self.server.backend.health())
            return
        if path == "/api/v1/cameras":
            self._json(HTTPStatus.OK, self.server.backend.cameras())
            return

        match = CAMERA_RE.fullmatch(path)
        if match:
            item = self.server.backend.camera(match.group(1))
            if item is None:
                self._error(HTTPStatus.NOT_FOUND, "camera_not_found", "Unknown camera stable_id.")
            else:
                self._json(HTTPStatus.OK, item)
            return

        match = STATUS_RE.fullmatch(path)
        if match:
            item = self.server.backend.camera_status(match.group(1))
            if item is None:
                self._error(HTTPStatus.NOT_FOUND, "camera_not_found", "Unknown camera stable_id.")
            else:
                self._json(HTTPStatus.OK, item)
            return

        self._error(HTTPStatus.NOT_FOUND, "not_found", "Unknown API endpoint.")

    def do_POST(self) -> None:  # noqa: N802
        path = self._preflight()
        if path is None:
            return
        length = self.headers.get("Content-Length")
        if length not in {None, "", "0"}:
            self._error(HTTPStatus.BAD_REQUEST, "body_not_supported", "This endpoint does not accept a request body.")
            return

        if path == "/api/v1/discover":
            try:
                result = self.server.backend.discover(fetch_tnp=True)
            except Exception:
                self._error(HTTPStatus.BAD_GATEWAY, "discovery_failed", "YI camera discovery failed.")
            else:
                self._json(HTTPStatus.OK, result)
            return

        for regex, operation in (
            (START_RE, "start"),
            (STOP_RE, "stop"),
            (RESTART_RE, "restart"),
        ):
            match = regex.fullmatch(path)
            if match:
                stable_id = match.group(1)
                if operation == "start":
                    status, payload = self.server.backend.start_camera(stable_id)
                elif operation == "stop":
                    status, payload = self.server.backend.stop_camera(stable_id)
                else:
                    status, payload = self.server.backend.restart_camera(stable_id)
                self._json(status, payload)
                return

        match = REPROBE_RE.fullmatch(path)
        if match:
            status, payload = self.server.backend.reprobe_camera(match.group(1))
            self._json(status, payload)
            return

        self._error(HTTPStatus.NOT_FOUND, "not_found", "Unknown API endpoint.")


def main() -> int:
    parser = argparse.ArgumentParser(description="YI Home Add-on backend API service")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--bind", default=os.getenv("YI_ADDON_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("YI_ADDON_PORT", "8099")))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--no-initial-discovery", action="store_true")
    parser.add_argument("--disable-lifecycle", action="store_true")
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--worker-dir", type=Path)
    parser.add_argument("--runtime-state-dir", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=45.0)
    parser.add_argument("--stall-timeout", type=float, default=12.0)
    parser.add_argument("--terminate-grace", type=float, default=3.0)
    parser.add_argument("--restart-delay", type=float, default=1.0)
    parser.add_argument("--max-restart-delay", type=float, default=30.0)
    parser.add_argument("--probe-duration", type=float, default=8.0)
    args = parser.parse_args()

    if args.env_file is not None:
        if not args.env_file.is_file():
            raise SystemExit(f"env file not found: {args.env_file}")
        oracle.load_env_file(args.env_file)

    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if args.probe_duration <= 0:
        raise SystemExit("--probe-duration must be greater than zero")

    token = os.getenv("YI_ADDON_API_TOKEN") or None
    if not _is_loopback(args.bind) and token is None:
        raise SystemExit("non-loopback bind requires YI_ADDON_API_TOKEN")

    lifecycle: YiRuntimeLifecycleManager | None = None
    capability_probe: YiCapabilityProbe | None = None
    capability_cache = YiCapabilityCache()
    if not args.disable_lifecycle:
        if args.env_file is None:
            raise SystemExit("--env-file is required unless --disable-lifecycle is used")
        config = build_default_config(
            env_file=args.env_file,
            root=Path(__file__).resolve().parent,
            runtime_root=args.runtime_root,
            worker_dir=args.worker_dir,
            state_dir=args.runtime_state_dir,
            startup_timeout=args.startup_timeout,
            stall_timeout=args.stall_timeout,
            terminate_grace=args.terminate_grace,
            restart_delay=args.restart_delay,
            max_restart_delay=args.max_restart_delay,
        )
        lifecycle = YiRuntimeLifecycleManager(config)
        capability_probe = YiCapabilityProbe(
            config,
            capability_cache,
            duration_seconds=args.probe_duration,
        )

    backend = YiAddonBackend(
        timeout=args.timeout,
        capability_cache=capability_cache,
        lifecycle=lifecycle,
        capability_probe=capability_probe,
    )
    if not args.no_initial_discovery:
        try:
            backend.discover(fetch_tnp=True)
        except Exception:
            # The service remains available so /health can report state and a
            # later POST /discover can recover from a temporary cloud outage.
            pass

    server = YiAddonHTTPServer((args.bind, args.port), backend, token)
    stopping = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        if stopping.is_set():
            return
        stopping.set()
        threading.Thread(target=server.shutdown, name="yi-addon-shutdown", daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    print(
        json.dumps(
            {
                "service": backend.SERVICE_NAME,
                "api_version": backend.API_VERSION,
                "bind": args.bind,
                "port": args.port,
                "authentication": "bearer" if token is not None else "loopback_only",
                "runtime_lifecycle_ready": lifecycle is not None,
                "reprobe_ready": capability_probe is not None,
                "secrets_exposed": False,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        backend.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
