"""Scan orchestration: target resolution, optional loopback static server, isolated worker process."""

from __future__ import annotations

import contextlib
import functools
import hashlib
import http.server
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .policy import PolicyError, Target, validate_target

PLUGIN_DIR = Path(__file__).resolve().parent
AXE_PATH = PLUGIN_DIR / "vendor" / "axe.min.js"
WORKER_PATH = PLUGIN_DIR / "worker.py"
VENDORED = PLUGIN_DIR / "vendor" / "VENDORED.json"
SENTINEL = "A11Y_LENS_RESULT:"

DEFAULT_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
MAX_TIMEOUT_S = 120
DEFAULT_TIMEOUT_S = 45
MAX_OUTPUT_BYTES = 40 * 1024 * 1024

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800, "mobile": False},
    "mobile": {"width": 390, "height": 844, "mobile": True},
}

# Environment variables the browser worker may inherit.  API keys and tokens are NOT among them.
_ENV_ALLOW = (
    "PATH", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR",
    "LANG", "LC_ALL", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "PLAYWRIGHT_BROWSERS_PATH",
    "FONTCONFIG_PATH", "LD_LIBRARY_PATH",
)


class ScanError(Exception):
    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


# ---------------------------------------------------------------------------------------------
# axe integrity
# ---------------------------------------------------------------------------------------------
def verify_vendored_axe() -> str:
    """Check the bundled axe-core against the recorded hash; returns its version."""
    meta = json.loads(VENDORED.read_text(encoding="utf-8"))["axe-core"]
    digest = hashlib.sha256(AXE_PATH.read_bytes()).hexdigest()
    if digest != meta["sha256"]:
        raise ScanError("axe_tampered", "vendor/axe.min.js does not match vendor/VENDORED.json; refusing to run an unverified engine.")
    return meta["version"]


# ---------------------------------------------------------------------------------------------
# Viewport / options
# ---------------------------------------------------------------------------------------------
def parse_viewport(spec: str | None) -> tuple[str, dict[str, Any]]:
    spec = (spec or "desktop").strip().lower()
    if spec in VIEWPORTS:
        return spec, dict(VIEWPORTS[spec])
    m = re.fullmatch(r"(\d{3,4})x(\d{3,4})", spec)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if 240 <= w <= 3840 and 240 <= h <= 2400:
            return spec, {"width": w, "height": h, "mobile": w < 600}
    raise ScanError("bad_viewport", f"viewport must be 'desktop', 'mobile' or WIDTHxHEIGHT (got {spec!r})")


# ---------------------------------------------------------------------------------------------
# Local static server (so Hermes can audit a file or folder with zero setup)
# ---------------------------------------------------------------------------------------------
class _ContainedHandler(http.server.SimpleHTTPRequestHandler):
    """Serves one directory, refusing symlink/`..` escapes and silencing logs."""

    root: str = "."

    def translate_path(self, path: str) -> str:  # noqa: D401
        resolved = os.path.realpath(super().translate_path(path))
        base = os.path.realpath(self.root)
        # Windows: case-insensitive filesystem; normcase makes containment check correct on Windows
        # while preserving POSIX behavior (normcase is a no-op there).
        if os.path.normcase(resolved) == os.path.normcase(base):
            return resolved
        if not os.path.normcase(resolved).startswith(os.path.normcase(base + os.sep)):
            return os.path.join(base, "__forbidden__")
        return resolved

    def log_message(self, *args: Any) -> None:  # silence
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


@contextlib.contextmanager
def serve_directory(directory: Path) -> Iterator[str]:
    """Serve ``directory`` on 127.0.0.1:<random port> for the duration of the block."""
    handler = type("Handler", (_ContainedHandler,), {"root": str(directory)})
    handler = functools.partial(handler, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


@dataclass
class Resolved:
    """What the user asked to scan, after resolving local paths."""

    label: str          # stable identity for comparisons (path or origin+path)
    kind: str           # "url" | "local"
    scan_url: str       # actual URL handed to the browser
    root: Path | None = None


def classify_input(raw: str, cwd: Path | None = None) -> tuple[str, Path | None]:
    raw = (raw or "").strip()
    if not raw:
        raise ScanError("bad_url", "url is required")
    if re.match(r"^https?://", raw, re.I):
        return "url", None
    candidate = raw[7:] if raw.lower().startswith("file://") else raw
    p = Path(os.path.expanduser(candidate))
    if not p.is_absolute():
        p = (cwd or Path.cwd()) / p
    if not p.exists():
        raise ScanError("not_found", f"{raw!r} is neither an http(s) URL nor an existing local file/folder.")
    p = p.resolve()
    # The page's directory is served on loopback, so be strict about WHAT may be served.
    if p.is_file() and p.suffix.lower() not in (".html", ".htm"):
        raise ScanError("not_html", f"Only .html/.htm files can be scanned locally (got {p.name!r}).")
    root = p if p.is_dir() else p.parent
    forbidden = {Path(root.anchor), Path.home().resolve()}
    if root in forbidden or len(root.parts) <= 2:
        raise ScanError("unsafe_root", f"Refusing to serve {root} (filesystem root, home directory or a top-level system folder). "
                        "Put the page in its own project folder.")
    return "local", p


# ---------------------------------------------------------------------------------------------
# Worker execution
# ---------------------------------------------------------------------------------------------
def _clean_env() -> dict[str, str]:
    return {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:  # pragma: no cover - windows
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(Exception):
            proc.kill()



def run_worker(job: dict[str, Any], hard_timeout_s: float) -> dict[str, Any]:
    popen_kwargs: dict[str, Any] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(
        [sys.executable, str(WORKER_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clean_env(),
        **popen_kwargs,
    )

    try:
        out_bytes, err_bytes = proc.communicate(
            json.dumps(job).encode("utf-8"),
            timeout=hard_timeout_s,
        )
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        with contextlib.suppress(Exception):
            proc.communicate(timeout=5)
        raise ScanError(
            "scan_timeout",
            f"Scan exceeded the hard limit of {int(hard_timeout_s)}s and was killed. "
            "No results were recorded as complete.",
        )
    finally:
        if proc.poll() is None:
            _kill_tree(proc)

    out_bytes = out_bytes or b""
    err_bytes = err_bytes or b""

    if len(out_bytes) > MAX_OUTPUT_BYTES:
        raise ScanError(
            "output_too_large",
            "Worker output exceeded the size cap; scan discarded.",
        )

    out = out_bytes.decode("utf-8", errors="replace")
    err = err_bytes.decode("utf-8", errors="replace")

    payload = None
    for line in reversed(out.splitlines()):
        if line.startswith(SENTINEL):
            try:
                payload = json.loads(line[len(SENTINEL):])
            except ValueError:
                payload = None
            break

    if payload is None:
        tail = (err or out).strip().splitlines()[-3:]
        raise ScanError(
            "worker_crash",
            f"Browser worker exited without a result (code {proc.returncode}).",
            details=tail,
        )

    return payload



def execute_scan(
    raw_target: str,
    *,
    allowed_origins: list[str],
    viewport: str | None = None,
    timeout_s: int | None = None,
    tags: list[str] | None = None,
    browser_executable: str | None = None,
    browser_channel: str | None = None,
    chromium_args: list[str] | None = None,
    settle_ms: int = 300,
    cwd: Path | None = None,
) -> dict[str, Any]:
    """Run one scan end-to-end and return ``{"resolved":…, "config":…, "worker":…}``.

    Raises :class:`PolicyError` / :class:`ScanError` for refusals and hard failures.  A worker that
    ran but could not finish returns normally with ``worker["status"] != "complete"``.
    """
    axe_version = verify_vendored_axe()
    vp_name, vp = parse_viewport(viewport)
    timeout = max(5, min(int(timeout_s or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S))
    kind, local_path = classify_input(raw_target, cwd)

    def _go(scan_url: str, label: str) -> dict[str, Any]:
        target: Target = validate_target(scan_url, allowed_origins)
        job = {
            "url": target.url,
            "pinned_hosts": target.pinned_hosts,
            "viewport": vp,
            "timeout_s": timeout,
            "tags": list(tags or DEFAULT_TAGS),
            "axe_path": str(AXE_PATH),
            "browser_executable": browser_executable or None,
            "browser_channel": browser_channel or None,
            "chromium_args": chromium_args or [],
            "settle_ms": settle_ms,
        }
        worker = run_worker(job, hard_timeout_s=timeout + 25)
        return {
            "resolved": {"label": label, "kind": kind, "scan_url": target.url, "origin": target.origin, "loopback": target.loopback},
            "config": {
                "viewport_name": vp_name, "viewport": vp, "timeout_s": timeout,
                "tags": job["tags"], "axe_version": axe_version, "settle_ms": settle_ms,
                "reduced_motion": True, "color_scheme": "light", "locale": "en-US", "timezone": "UTC",
            },
            "worker": worker,
        }

    if kind == "url":
        label = raw_target.strip()
        return _go(raw_target.strip(), label)

    assert local_path is not None
    root = local_path if local_path.is_dir() else local_path.parent
    rel = "" if local_path.is_dir() else local_path.name
    if local_path.is_dir() and not (local_path / "index.html").exists():
        raise ScanError("no_index", f"{local_path} has no index.html; pass the HTML file itself.")
    with serve_directory(root) as base:
        return _go(f"{base}/{rel}", str(local_path))
