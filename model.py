"""Turn raw worker output into a stable, queryable scan record (no model involvement)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .store import utc_now

IMPACT_ORDER = ["critical", "serious", "moderate", "minor"]
IMPACT_RANK = {name: i for i, name in enumerate(IMPACT_ORDER)}

DISCLAIMER = (
    "Automated testing (axe-core) can only detect a portion of WCAG issues. A scan with no violations is NOT "
    "a conformance claim or certification; keyboard, screen-reader, zoom/reflow and content-quality checks still "
    "need a human. Items under 'needs human review' were NOT decided by the engine."
)

# Deterministic, hand-written remediation examples for the most common rules.  axe's own
# failureSummary / helpUrl is always included as well; these only add a concrete code pattern.
FIX_HINTS: dict[str, str] = {
    "button-name": 'Give the button visible text or an accessible name: <button aria-label="Close dialog">…</button>.',
    "link-name": 'Give the link discernible text (or aria-label on icon-only links): <a href="/cart" aria-label="Cart">…</a>.',
    "image-alt": 'Add alt text describing the image\'s purpose (alt="" if purely decorative): <img src="x.png" alt="Team photo, 2026 offsite">.',
    "label": 'Associate a label with the control: <label for="email">Email</label><input id="email" type="email">.',
    "select-name": 'Associate a <label for=…> or aria-label with the <select>.',
    "color-contrast": "Increase foreground/background contrast to at least 4.5:1 (3:1 for large text). The evidence lists the measured ratio and colours.",
    "html-has-lang": 'Declare the page language: <html lang="en">.',
    "document-title": "Add a descriptive, unique <title> inside <head>.",
    "heading-order": "Do not skip heading levels (h1 → h2 → h3). Restyle with CSS instead of picking a smaller tag.",
    "page-has-heading-one": "Add one <h1> that names the page.",
    "landmark-one-main": "Wrap the primary content in a single <main> element.",
    "region": "Place all visible content inside landmarks (<header>, <nav>, <main>, <footer>).",
    "aria-allowed-attr": "Remove ARIA attributes that are not valid for the element's role.",
    "aria-valid-attr-value": "Use a valid value for the ARIA attribute (e.g. aria-labelledby must reference an existing id).",
    "aria-required-attr": "Add the ARIA attributes this role requires (e.g. role=checkbox needs aria-checked).",
    "aria-roles": "Use a valid WAI-ARIA role value.",
    "duplicate-id": "Make every id on the page unique.",
    "meta-viewport": "Do not disable zoom: remove user-scalable=no / maximum-scale=1 from the viewport meta tag.",
    "tabindex": "Avoid tabindex values greater than 0; use DOM order for focus order.",
    "scrollable-region-focusable": 'Make scrollable regions keyboard reachable: add tabindex="0" (and a role/label) to the container.',
    "frame-title": "Give each <iframe> a descriptive title attribute.",
    "list": "Only <li> (and script/template) may be direct children of <ul>/<ol>.",
    "listitem": "Wrap <li> elements in a <ul> or <ol>.",
    "bypass": 'Provide a "skip to main content" link or landmark navigation.',
    "empty-heading": "Give the heading discernible text or remove it.",
    "input-image-alt": 'Add alt text to <input type="image">.',
    "target-size": "Make the interactive target at least 24×24 CSS px (or add spacing).",
}

_WCAG_SC = re.compile(r"^wcag(\d)(\d)(\d+)$")
_WCAG_LEVEL = {"wcag2a": ("2.0", "A"), "wcag2aa": ("2.0", "AA"), "wcag2aaa": ("2.0", "AAA"),
               "wcag21a": ("2.1", "A"), "wcag21aa": ("2.1", "AA"), "wcag22aa": ("2.2", "AA")}
_VOLATILE_ATTR = re.compile(r"""\s(?:class|style|nonce|data-[\w-]+)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)""", re.I)


def wcag_info(tags: list[str]) -> dict[str, Any]:
    criteria = sorted({f"{m.group(1)}.{m.group(2)}.{m.group(3)}" for t in tags if (m := _WCAG_SC.match(t))},
                      key=lambda s: [int(x) for x in s.split(".")])
    levels = [(_WCAG_LEVEL[t]) for t in tags if t in _WCAG_LEVEL]
    category = "wcag" if levels or criteria else ("best-practice" if "best-practice" in tags else "other")
    return {
        "criteria": criteria,
        "level": levels[0][1] if levels else None,
        "since": levels[0][0] if levels else None,
        "category": category,
    }


def normalize_html(html: str) -> str:
    h = _VOLATILE_ATTR.sub("", html or "")
    return re.sub(r"\s+", " ", h).strip().lower()


def _fp(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _node(rule_id: str, n: dict[str, Any], dom: dict[str, Any], shots: dict[str, str]) -> dict[str, Any]:
    target = [t if isinstance(t, str) else "|".join(t) for t in n["target"]]
    selector = " >> ".join(target)
    evidence = dom.get(target[0]) if len(target) == 1 else None
    checks = []
    for c in n.get("checks", []):
        item = {"kind": c["kind"], "id": c["id"], "message": c["message"]}
        if c.get("data") not in (None, {}, []):
            item["data"] = c["data"]
        checks.append(item)
    return {
        "selector": selector,
        "target": target,
        "html": n["html"],
        "impact": n.get("impact"),
        "failure_summary": n.get("failureSummary", ""),
        "checks": checks,
        "evidence": evidence,
        "has_screenshot": len(target) == 1 and target[0] in shots,
        "fingerprint": {
            "selector_key": _fp(rule_id, selector),
            "html_key": _fp(rule_id, normalize_html(n["html"])),
        },
    }


def _rule(r: dict[str, Any], dom: dict[str, Any], shots: dict[str, str]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "impact": r.get("impact"),
        "help": r["help"],
        "description": r["description"],
        "help_url": r["helpUrl"],
        "tags": r["tags"],
        "wcag": wcag_info(r["tags"]),
        "fix_hint": FIX_HINTS.get(r["id"]),
        "node_count": r.get("node_count", len(r["nodes"])),
        "nodes": [_node(r["id"], n, dom, shots) for n in r["nodes"]],
    }


def _impact_counts(rules: list[dict[str, Any]], *, instances: bool) -> dict[str, int]:
    out = {k: 0 for k in IMPACT_ORDER}
    for r in rules:
        for n in r["nodes"] if instances else [None]:
            key = (n["impact"] if n else r["impact"]) or "minor"
            if key in out:
                out[key] += 1
        if instances and r["node_count"] > len(r["nodes"]):
            out[r["impact"] or "minor"] += r["node_count"] - len(r["nodes"])
    return out


def build_record(execution: dict[str, Any] | None, *, error: dict[str, Any] | None = None,
                 target: dict[str, Any] | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a scan record from ``runner.execute_scan`` output (or from a pre-flight failure)."""
    created = utc_now()
    if execution is None:
        return {
            "id": None, "created_at": created, "status": "failed", "error": error,
            "target": target or {"label": "unknown", "scan_url": "", "kind": "url"},
            "config": config or {}, "browser": {}, "page": {}, "violations": [], "review": [], "passes": [],
            "summary": _empty_summary(), "coverage": {}, "blocked_requests": [], "console_errors": [],
            "notes": [], "incomplete_reasons": [], "evidence_truncation": {"truncated": False, "omitted_nodes": 0, "by_rule": []}, "disclaimer": DISCLAIMER, "screenshots": {}, "duration_ms": 0,
        }

    w = execution["worker"]
    resolved = execution["resolved"]
    axe = w.get("axe")
    dom = w.get("dom_evidence") or {}
    shots = w.get("screenshots") or {}
    violations = sorted((_rule(r, dom, shots) for r in (axe or {}).get("violations", [])),
                        key=lambda r: (IMPACT_RANK.get(r["impact"] or "minor", 9), r["id"]))
    review = sorted((_rule(r, dom, shots) for r in (axe or {}).get("incomplete", [])), key=lambda r: r["id"])
    passes = [{"id": p["id"], "help": p["help"], "nodes": p["nodes"]} for p in (axe or {}).get("passes", [])]

    summary = {
        "rules_violated": len(violations),
        "instances": sum(r["node_count"] for r in violations),
        "by_impact_rules": _impact_counts(violations, instances=False),
        "by_impact_instances": _impact_counts(violations, instances=True),
        "needs_review_rules": len(review),
        "needs_review_instances": sum(r["node_count"] for r in review),
        "rules_passed": len(passes),
        "rules_inapplicable": len((axe or {}).get("inapplicable", [])),
    }
    status = w.get("status", "failed")
    err = w.get("error")
    if status == "complete" and axe is None:  # defensive: never call a result-less scan complete
        status, err = "failed", {"code": "no_axe_result", "message": "Worker reported success without axe results."}

    # Evidence truncation is NOT a coverage gap: compute explicit metadata.
    # Prefer worker-provided evidence_truncation; fall back to deriving from node_count vs stored nodes.
    trunc = w.get("evidence_truncation")
    if not isinstance(trunc, dict):
        # Fallback for older records: derive from violations/review
        omitted = 0
        by_rule: list[dict[str, object]] = []
        for bucket_name, bucket in (("violations", violations), ("review", review)):
            for r in bucket:
                if r["node_count"] > len(r["nodes"]):
                    diff = r["node_count"] - len(r["nodes"])
                    omitted += diff
                    by_rule.append({"id": r["id"], "bucket": bucket_name, "omitted": diff, "total": r["node_count"]})
        trunc = {"truncated": omitted > 0, "omitted_nodes": omitted, "by_rule": by_rule}
    else:
        # Ensure required keys exist
        trunc = {
            "truncated": bool(trunc.get("truncated")),
            "omitted_nodes": int(trunc.get("omitted_nodes", 0)),
            "by_rule": list(trunc.get("by_rule", [])),
        }
        # If worker truncated flag is false but node_counts indicate truncation (old data), reconcile
        # by recomputing; prefer the explicit derivation to avoid silent loss.
        derived_omitted = sum(max(0, r["node_count"] - len(r["nodes"])) for r in violations + review)
        if derived_omitted != trunc["omitted_nodes"]:
            # Re-derive (handles legacy records where worker field missing or inconsistent)
            omitted = derived_omitted
            by_rule = []
            for bucket_name, bucket in (("violations", violations), ("review", review)):
                for r in bucket:
                    if r["node_count"] > len(r["nodes"]):
                        diff = r["node_count"] - len(r["nodes"])
                        by_rule.append({"id": r["id"], "bucket": bucket_name, "omitted": diff, "total": r["node_count"]})
            trunc = {"truncated": omitted > 0, "omitted_nodes": omitted, "by_rule": by_rule}

    return {
        "id": None,
        "created_at": created,
        "status": status,
        "error": err,
        "target": {"label": resolved["label"], "scan_url": resolved["scan_url"], "kind": resolved["kind"],
                   "origin": resolved["origin"], "loopback": resolved["loopback"]},
        "config": execution["config"],
        "browser": w.get("browser", {}),
        "page": w.get("page", {}),
        "violations": violations,
        "review": review,
        "passes": passes,
        "summary": summary,
        "coverage": w.get("coverage", {}),
        "blocked_requests": w.get("blocked_requests", []),
        "console_errors": w.get("console_errors", []),
        "notes": w.get("notes", []),
        "incomplete_reasons": w.get("incomplete_reasons", []),
        "evidence_truncation": trunc,
        "disclaimer": DISCLAIMER,
        "screenshots": shots,
        "duration_ms": w.get("duration_ms", 0),
    }


def _empty_summary() -> dict[str, Any]:
    z = {k: 0 for k in IMPACT_ORDER}
    return {"rules_violated": 0, "instances": 0, "by_impact_rules": dict(z), "by_impact_instances": dict(z),
            "needs_review_rules": 0, "needs_review_instances": 0, "rules_passed": 0, "rules_inapplicable": 0}
