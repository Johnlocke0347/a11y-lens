"""Business logic behind the three tools.  Pure functions returning JSON-serialisable dicts; no Hermes
imports, so everything here is unit-testable and reusable from the CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import runner
from .compare import CompareError, compare_scans
from .model import IMPACT_ORDER, build_record
from .policy import PolicyError
from .report import render_compare_html, render_scan_html, render_scan_json
from .store import Store, parse_scan_id, scan_id_for

MAX_RULES_IN_SCAN_REPLY = 12
MAX_NODES_IN_SCAN_REPLY = 3


@dataclass
class Settings:
    allowed_origins: list[str] = field(default_factory=list)
    browser_executable: str = ""
    browser_channel: str = ""
    chromium_args: list[str] = field(default_factory=list)
    default_timeout_s: int = runner.DEFAULT_TIMEOUT_S
    keep_scans: int = 100


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _write_reports(store: Store, scan: dict[str, Any]) -> dict[str, str]:
    html_path = store.report_path(scan["id"], "html")
    json_path = store.report_path(scan["id"], "json")
    html_path.write_text(render_scan_html(scan), encoding="utf-8")
    json_path.write_text(render_scan_json(scan), encoding="utf-8")
    return {"report_html": str(html_path), "report_json": str(json_path)}


def _rule_brief(rule: dict[str, Any], max_nodes: int) -> dict[str, Any]:
    return {
        "rule_id": rule["id"], "impact": rule["impact"], "help": rule["help"],
        "wcag": rule["wcag"]["criteria"] or [rule["wcag"]["category"]],
        "elements_affected": rule["node_count"],
        "fix_pattern": rule.get("fix_hint"),
        "docs": rule["help_url"],
        "elements": [
            {"selector": n["selector"], "html": _clip(n["html"], 220), "why": _clip(n["failure_summary"], 320)}
            for n in rule["nodes"][:max_nodes]
        ],
    }


# ---------------------------------------------------------------------------------------------
def scan(store: Store, settings: Settings, url: str, viewport: str | None = None,
         timeout_s: int | None = None, note: str | None = None, cwd: Path | None = None) -> dict[str, Any]:
    try:
        execution = runner.execute_scan(
            url, allowed_origins=settings.allowed_origins, viewport=viewport,
            timeout_s=timeout_s or settings.default_timeout_s,
            browser_executable=settings.browser_executable or None, browser_channel=settings.browser_channel or None,
            chromium_args=settings.chromium_args, cwd=cwd,
        )
        record = build_record(execution)
    except PolicyError as exc:  # refused before anything ran -> not a scan, nothing stored
        return {"ok": False, "refused": True, "error": {"code": exc.code, "message": str(exc)},
                "message": "Scan refused by A11Y Lens safety policy. No scan was run."}
    except runner.ScanError as exc:
        if exc.code in ("bad_url", "not_found", "no_index", "bad_viewport", "axe_tampered", "not_html", "unsafe_root"):
            return {"ok": False, "error": {"code": exc.code, "message": str(exc)}, "message": "No scan was run."}
        record = build_record(None, error={"code": exc.code, "message": str(exc), "details": exc.details},
                              target={"label": url, "scan_url": url, "kind": "url"})
    if note:
        record["note"] = _clip(note, 200)
    scan_id = store.save(record, keep=settings.keep_scans)
    files = _write_reports(store, record)

    s = record["summary"]
    out: dict[str, Any] = {
        "ok": record["status"] in ("complete", "incomplete"),
        "scan_id": scan_id,
        "status": record["status"],
        "target": record["target"]["label"],
        "scanned_url": record["target"]["scan_url"],
        "viewport": record["config"].get("viewport_name"),
        "engine": f"axe-core {record['config'].get('axe_version')}",
        "browser": f"{record['browser'].get('name', '')} {record['browser'].get('version', '')}".strip(),
        "disclaimer": record["disclaimer"],
        **files,
    }
    if record["status"] == "failed":
        out["error"] = record["error"]
        out["message"] = "The scan FAILED. No accessibility audit was completed; do not report any result for this target."
        return out
    out["summary"] = {
        "rules_violated": s["rules_violated"], "elements_affected": s["instances"],
        "by_impact_elements": s["by_impact_instances"], "needs_human_review_rules": s["needs_review_rules"],
        "rules_passed": s["rules_passed"],
    }
    if record["status"] == "incomplete":
        out["message"] = "The scan is INCOMPLETE; findings below are real but coverage is partial. Do not call this a full audit."
        out["incomplete_reasons"] = record["incomplete_reasons"]
    out["findings"] = [_rule_brief(r, MAX_NODES_IN_SCAN_REPLY) for r in record["violations"][:MAX_RULES_IN_SCAN_REPLY]]
    if len(record["violations"]) > MAX_RULES_IN_SCAN_REPLY:
        out["findings_truncated"] = f"{len(record['violations']) - MAX_RULES_IN_SCAN_REPLY} more rule(s); use a11y_report(scan_id) for all."
    out["needs_human_review"] = [{"rule_id": r["id"], "help": r["help"], "elements": r["node_count"]} for r in record["review"]]
    warn = list(record["notes"])
    if record["blocked_requests"]:
        warn.append(f"{len(record['blocked_requests'])} off-origin request(s) blocked (policy).")
    if warn:
        out["warnings"] = warn
    out["next_steps"] = ("Fix issues with your normal file tools, then call a11y_scan again on the same target and "
                         f"a11y_compare(before_id='{scan_id}', after_id=<new scan id>) to verify in the rendered page.")
    return out


# ---------------------------------------------------------------------------------------------
def report(store: Store, scan_id: Any = None, rule_id: str | None = None, impact: str | None = None,
           include: str = "violations", limit: int = 8, offset: int = 0) -> dict[str, Any]:
    if scan_id in (None, "", "list"):
        return {"ok": True, "scans": store.list(limit=20),
                "message": "Recent scans (newest first). Pass scan_id to a11y_report for details."}
    rec = _resolve(store, scan_id)
    if rec is None:
        return {"ok": False, "error": {"code": "scan_not_found", "message": f"No scan matching {scan_id!r}."},
                "recent": store.list(limit=5)}
    if impact and impact not in IMPACT_ORDER:
        return {"ok": False, "error": {"code": "bad_impact", "message": f"impact must be one of {IMPACT_ORDER}"}}
    include = include if include in ("violations", "review", "passes", "all") else "violations"
    limit = max(1, min(int(limit or 8), 25))
    offset = max(0, int(offset or 0))

    files = {"report_html": str(store.report_path(rec["id"], "html")), "report_json": str(store.report_path(rec["id"], "json"))}
    if not Path(files["report_html"]).exists():
        files = _write_reports(store, rec)

    out: dict[str, Any] = {
        "ok": True, "scan_id": rec["id"], "status": rec["status"], "created_at": rec["created_at"],
        "target": rec["target"]["label"], "config": rec["config"], "summary": rec["summary"],
        "disclaimer": rec["disclaimer"], **files,
    }
    if rec["status"] != "complete":
        out["warning"] = f"This scan is {rec['status']}: " + (rec.get("error") or {}).get("message", "; ".join(rec["incomplete_reasons"]))
    pools: list[tuple[str, list[dict[str, Any]]]] = []
    if include in ("violations", "all"):
        pools.append(("violations", rec["violations"]))
    if include in ("review", "all"):
        pools.append(("needs_human_review", rec["review"]))
    for name, rules in pools:
        sel = [r for r in rules if (not rule_id or r["id"] == rule_id) and (not impact or r["impact"] == impact)]
        page = sel[offset: offset + limit]
        out[name] = [
            {**{k: r[k] for k in ("id", "impact", "help", "description", "help_url", "fix_hint", "node_count")},
             "wcag": r["wcag"],
             "nodes": [{"selector": n["selector"], "html": n["html"], "impact": n["impact"],
                        "failure_summary": n["failure_summary"], "evidence": n["evidence"],
                        "checks": [c for c in n["checks"] if "data" in c]} for n in r["nodes"][:10]]}
            for r in page
        ]
        out[f"{name}_total_matching"] = len(sel)
        if offset + limit < len(sel):
            out[f"{name}_next_offset"] = offset + limit
    if include in ("passes", "all"):
        out["passes"] = [{"rule_id": p["id"], "help": p["help"], "elements": p["nodes"]} for p in rec["passes"]]
    if rec.get("blocked_requests"):
        out["blocked_requests"] = rec["blocked_requests"][:20]
    if rec.get("console_errors"):
        out["page_console_errors"] = rec["console_errors"][:10]
    return out


# ---------------------------------------------------------------------------------------------
def _resolve(store: Store, ref: Any, *, complete_only: bool = False) -> dict[str, Any] | None:
    if str(ref).strip().lower() == "latest":
        return store.latest(status="complete" if complete_only else None)
    return store.get(ref)


def compare(store: Store, before_id: Any, after_id: Any = "latest") -> dict[str, Any]:
    after = _resolve(store, after_id or "latest", complete_only=True)
    if after is None:
        return {"ok": False, "error": {"code": "scan_not_found", "message": f"No scan matching after_id={after_id!r}."}}
    if str(before_id).strip().lower() in ("previous", "prev", "baseline"):
        n = parse_scan_id(after["id"])
        before = store.latest(after["target"]["label"], status="complete", before_n=n)
    else:
        before = store.get(before_id)
    if before is None:
        return {"ok": False, "error": {"code": "scan_not_found", "message": f"No scan matching before_id={before_id!r}."},
                "recent": store.list(limit=5)}
    try:
        cmp = compare_scans(before, after)
    except CompareError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    path = store.report_path(f"compare-{before['id']}-vs-{after['id']}", "html")
    path.write_text(render_compare_html(cmp), encoding="utf-8")
    jpath = store.report_path(f"compare-{before['id']}-vs-{after['id']}", "json")
    jpath.write_text(json.dumps(cmp, indent=2, ensure_ascii=False), encoding="utf-8")
    cap = 25
    out = {k: cmp[k] for k in ("before_id", "after_id", "target", "verdict", "summary", "warnings", "caveat", "by_rule", "severity_changed")}
    for k in ("introduced", "resolved", "remaining"):
        out[k] = [{kk: vv for kk, vv in i.items() if kk != "wcag"} | {"html": _clip(i["html"], 180)} for i in cmp[k][:cap]]
        if len(cmp[k]) > cap:
            out[f"{k}_truncated"] = f"{len(cmp[k]) - cap} more in the JSON report"
    out.update({"ok": True, "report_html": str(path), "report_json": str(jpath)})
    return out
