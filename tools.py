"""Hermes-facing tool schemas and handlers.  Handlers never raise and always return a JSON string."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from . import service
from .store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------------------------
SCAN_SCHEMA = {
    "name": "a11y_scan",
    "description": (
        "Audit a web page for accessibility (WCAG) problems by opening it in a REAL headless Chromium and running "
        "the axe-core engine against the rendered DOM. Findings are deterministic engine output with CSS selectors, "
        "HTML snippets and measured evidence (e.g. contrast ratios) - never guessed. `url` may be a localhost URL "
        "(http://localhost:3000), or a local .html file / folder path (A11Y Lens serves it on a temporary loopback "
        "server for the scan). Remote sites are refused unless a human authorised the origin with `hermes a11y allow`. "
        "Returns a scan_id, severity counts, top findings with selectors and fix patterns, and paths to a JSON and an "
        "HTML report. A scan with status other than 'complete' is NOT a finished audit and must be reported as such. "
        "Never claims WCAG conformance. After fixing code with your normal file tools, call a11y_scan again on the "
        "same target and then a11y_compare to prove the fix in the rendered page."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "http(s) URL on localhost, an authorised origin, or an absolute path to an .html file or a folder containing index.html."},
            "viewport": {"type": "string", "description": "'desktop' (1280x800, default), 'mobile' (390x844) or 'WIDTHxHEIGHT'. Use the same viewport for before/after scans."},
            "timeout_s": {"type": "integer", "description": "Page-load budget in seconds (5-120, default 45). A hard process-level limit is enforced on top."},
            "note": {"type": "string", "description": "Optional short label stored with the scan, e.g. 'baseline' or 'after fixing buttons'."},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
}

REPORT_SCHEMA = {
    "name": "a11y_report",
    "description": (
        "Retrieve the full stored evidence of a previous a11y_scan: every violating element with selector, HTML, "
        "failure explanation, measured data, WCAG criteria and fix pattern. Filter by rule_id or impact. Use "
        "include='review' for items axe could not decide (need a human). Call with no scan_id to list recent scans. "
        "Also returns paths to the saved JSON and self-contained HTML report files."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scan_id": {"type": "string", "description": "e.g. 'scan-0003', or 'latest'. Omit to list recent scans."},
            "rule_id": {"type": "string", "description": "Only this axe rule, e.g. 'color-contrast'."},
            "impact": {"type": "string", "enum": ["critical", "serious", "moderate", "minor"]},
            "include": {"type": "string", "enum": ["violations", "review", "passes", "all"], "description": "Default 'violations'."},
            "limit": {"type": "integer", "description": "Max rules per page (1-25, default 8)."},
            "offset": {"type": "integer", "description": "Skip this many rules (pagination)."},
        },
        "additionalProperties": False,
    },
}

COMPARE_SCHEMA = {
    "name": "a11y_compare",
    "description": (
        "Compare two completed scans of the same target and report which violations were RESOLVED, which REMAIN, and "
        "which were NEWLY INTRODUCED (regressions), plus severity changes. Elements are matched by rule + selector, "
        "then normalised HTML, then tag+text, so fixes that shift selectors are not misreported. Refuses to compare "
        "incomplete or failed scans. 'Resolved' means the automated check stopped failing in the rendered page, not "
        "that the fix is semantically ideal. Use this after re-scanning to verify a repair; report regressions honestly."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "before_id": {"type": "string", "description": "Baseline scan id, or 'previous' for the last complete scan of the same target before after_id."},
            "after_id": {"type": "string", "description": "Scan id after the change; default 'latest' (newest complete scan)."},
        },
        "required": ["before_id"],
        "additionalProperties": False,
    },
}

TOOLS = (("a11y_scan", SCAN_SCHEMA, "🔎"), ("a11y_report", REPORT_SCHEMA, "📋"), ("a11y_compare", COMPARE_SCHEMA, "⚖️"))


# ---------------------------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------------------------
class Runtime:
    """Holds the lazily-opened store and reads user settings fresh on every call."""

    def __init__(self, ctx: Any = None, store: Store | None = None, settings_fn: Callable[[], service.Settings] | None = None):
        self._ctx = ctx
        self._store = store
        self._lock = threading.Lock()
        self._settings_fn = settings_fn

    @property
    def store(self) -> Store:
        with self._lock:
            if self._store is None:
                self._store = Store.open_default()
            return self._store

    def settings(self) -> service.Settings:
        if self._settings_fn:
            return self._settings_fn()
        ctx = self._ctx
        get = (lambda k, d: ctx.get_config(k, default=d)) if ctx is not None else (lambda k, d: d)

        def _list(v: Any) -> list[str]:
            return [str(x) for x in v] if isinstance(v, (list, tuple)) else []

        def _int(v: Any, d: int) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return d

        return service.Settings(
            allowed_origins=_list(get("allowed_origins", [])),
            browser_executable=str(get("browser_executable", "") or ""),
            browser_channel=str(get("browser_channel", "") or ""),
            chromium_args=_list(get("chromium_args", [])),
            default_timeout_s=_int(get("default_timeout_s", 45), 45),
            keep_scans=_int(get("keep_scans", 100), 100),
        )


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def make_handlers(rt: Runtime) -> dict[str, Callable[..., str]]:
    def guarded(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[..., str]:
        def handler(args: dict[str, Any] | None = None, **_kw: Any) -> str:
            try:
                return _json(fn(args or {}))
            except Exception as exc:  # noqa: BLE001 - tool contract: never raise
                logger.exception("a11y-lens tool failed")
                return _json({"ok": False, "error": {"code": "internal_error", "message": f"{type(exc).__name__}: {exc}"}})
        return handler

    def scan(a: dict[str, Any]) -> dict[str, Any]:
        target = a.get("url") or a.get("target")  # tolerate the obvious alias
        if not target:
            return {"ok": False, "error": {"code": "bad_args", "message": "url is required"}}
        base = os.environ.get("TERMINAL_CWD")  # where the agent's terminal currently is, if known
        cwd = Path(base) if base and Path(base).is_dir() else None
        return service.scan(rt.store, rt.settings(), str(target), viewport=a.get("viewport"),
                            timeout_s=a.get("timeout_s"), note=a.get("note"), cwd=cwd)

    def report(a: dict[str, Any]) -> dict[str, Any]:
        return service.report(rt.store, a.get("scan_id"), rule_id=a.get("rule_id"), impact=a.get("impact"),
                              include=a.get("include") or "violations", limit=a.get("limit") or 8, offset=a.get("offset") or 0)

    def compare(a: dict[str, Any]) -> dict[str, Any]:
        if not a.get("before_id"):
            return {"ok": False, "error": {"code": "bad_args", "message": "before_id is required"}}
        return service.compare(rt.store, a["before_id"], a.get("after_id") or "latest")

    return {"a11y_scan": guarded(scan), "a11y_report": guarded(report), "a11y_compare": guarded(compare)}
