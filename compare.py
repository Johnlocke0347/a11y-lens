"""Before/after comparison of two scan records.

Matching is deliberately NOT index- or selector-only, because fixing code shifts selectors.  For each
rule, nodes are paired in three passes (each element is matched at most once):

1. ``selector``  - same rule + same CSS target
2. ``html``      - same rule + same normalised outerHTML (survives re-ordering / wrapper changes)
3. ``text-tag``  - same rule + same tag + same visible text (survives attribute rewrites)

Anything left in *before* is **resolved**; anything left in *after* is **introduced**.  Every
remaining pair records which pass matched it, so the evidence of a "remaining" claim is visible.
"""

from __future__ import annotations

from typing import Any

from .model import IMPACT_RANK


class CompareError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _flat(scan: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in scan["violations"]:
        for n in r["nodes"]:
            out.append({"rule_id": r["id"], "rule_help": r["help"], "wcag": r["wcag"], "node": n,
                        "impact": n.get("impact") or r.get("impact") or "minor"})
    return out


def _text_tag_key(item: dict[str, Any]) -> str | None:
    ev = item["node"].get("evidence")
    if not ev or not ev.get("text"):
        return None
    return f"{item['rule_id']}|{ev['tag']}|{ev['text']}"


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    n = item["node"]
    return {"rule_id": item["rule_id"], "help": item["rule_help"], "impact": item["impact"],
            "selector": n["selector"], "html": n["html"], "wcag": item["wcag"]["criteria"]}


def compare_scans(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    for name, s in (("before", before), ("after", after)):
        if s["status"] != "complete":
            raise CompareError(
                "scan_not_complete",
                f"The {name} scan ({s.get('id')}) has status '{s['status']}', not 'complete'. "
                "Comparing against a partial or failed scan would give misleading verdicts; re-scan first.",
            )

    warnings: list[str] = []
    if before["target"]["label"] != after["target"]["label"]:
        warnings.append(f"Different targets: {before['target']['label']} vs {after['target']['label']}. Results compare two different pages.")
    bc, ac = before["config"], after["config"]
    if bc.get("viewport") != ac.get("viewport"):
        warnings.append("Different viewports; responsive differences can look like fixes or regressions.")
    if sorted(bc.get("tags", [])) != sorted(ac.get("tags", [])):
        warnings.append("Different rule tag sets; rule coverage differs between scans.")
    if bc.get("axe_version") != ac.get("axe_version"):
        warnings.append(f"Different axe-core versions ({bc.get('axe_version')} vs {ac.get('axe_version')}); rule behaviour may differ.")
    for s, name in ((before, "before"), (after, "after")):
        if s["summary"]["instances"] > sum(len(r["nodes"]) for r in s["violations"]):
            warnings.append(f"The {name} scan stored fewer nodes than were found (per-rule cap); counts stay accurate but matching is approximate for the overflow.")
        if s.get("blocked_requests"):
            warnings.append(f"The {name} scan blocked {len(s['blocked_requests'])} off-origin request(s); rendering may differ from production.")

    b_items, a_items = _flat(before), _flat(after)
    b_left, a_left = list(range(len(b_items))), list(range(len(a_items)))
    pairs: list[tuple[int, int, str]] = []

    def run_pass(name: str, key_fn) -> None:
        nonlocal b_left, a_left
        index: dict[str, list[int]] = {}
        for j in a_left:
            k = key_fn(a_items[j])
            if k is not None:
                index.setdefault(k, []).append(j)
        used_a: set[int] = set()
        used_b: set[int] = set()
        for i in b_left:
            k = key_fn(b_items[i])
            if k is None:
                continue
            cands = [j for j in index.get(k, []) if j not in used_a]
            if cands:
                j = cands[0]
                used_a.add(j); used_b.add(i)
                pairs.append((i, j, name))
        b_left = [i for i in b_left if i not in used_b]
        a_left = [j for j in a_left if j not in used_a]

    run_pass("selector", lambda it: it["node"]["fingerprint"]["selector_key"])
    run_pass("html", lambda it: it["node"]["fingerprint"]["html_key"])
    run_pass("text-tag", _text_tag_key)

    remaining, severity_changed = [], []
    for i, j, how in sorted(pairs):
        bi, ai = b_items[i], a_items[j]
        entry = _brief(ai) | {"matched_by": how, "before_selector": bi["node"]["selector"]}
        if bi["impact"] != ai["impact"]:
            entry["impact_before"] = bi["impact"]
            severity_changed.append(entry)
        remaining.append(entry)
    resolved = [_brief(b_items[i]) for i in b_left]
    introduced = [_brief(a_items[j]) for j in a_left]

    def by_rule() -> list[dict[str, Any]]:
        rules: dict[str, dict[str, Any]] = {}
        def slot(it):
            return rules.setdefault(it["rule_id"], {"rule_id": it["rule_id"], "help": it["rule_help"], "before": 0, "after": 0})
        for it in b_items: slot(it)["before"] += 1
        for it in a_items: slot(it)["after"] += 1
        for r in rules.values():
            r["delta"] = r["after"] - r["before"]
            r["state"] = ("fixed" if r["after"] == 0 else "new" if r["before"] == 0
                          else "improved" if r["delta"] < 0 else "worse" if r["delta"] > 0 else "unchanged")
        return sorted(rules.values(), key=lambda r: (r["delta"], r["rule_id"]))

    if introduced and resolved:
        verdict = "mixed"
    elif introduced:
        verdict = "regressed"
    elif resolved:
        verdict = "improved"
    else:
        verdict = "unchanged"

    sev_rank = lambda it: IMPACT_RANK.get(it["impact"], 9)  # noqa: E731
    return {
        "before_id": before["id"], "after_id": after["id"],
        "before_at": before["created_at"], "after_at": after["created_at"],
        "target": after["target"]["label"],
        "verdict": verdict,
        "summary": {
            "before_instances": len(b_items), "after_instances": len(a_items),
            "resolved": len(resolved), "remaining": len(remaining), "introduced": len(introduced),
            "severity_changed": len(severity_changed),
            "net_change": len(a_items) - len(b_items),
            "rules_fixed_completely": sum(1 for r in by_rule() if r["state"] == "fixed"),
            "needs_review_before": before["summary"]["needs_review_instances"],
            "needs_review_after": after["summary"]["needs_review_instances"],
        },
        "resolved": sorted(resolved, key=sev_rank),
        "remaining": sorted(remaining, key=sev_rank),
        "introduced": sorted(introduced, key=sev_rank),
        "severity_changed": severity_changed,
        "by_rule": by_rule(),
        "warnings": warnings,
        "caveat": ("'Resolved' means the automated check no longer fails in the rendered page; it does not prove the fix is "
                   "semantically good (e.g. meaningful alt text) and is not a conformance claim."),
    }
