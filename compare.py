"""Before/after comparison of two scan records.

Matching is deliberately NOT index- or selector-only, because fixing code shifts selectors.  For each
rule, nodes are paired in three passes (each element is matched at most once):

1. ``selector``  - same rule + same CSS target
2. ``html``      - same rule + same normalised outerHTML (survives re-ordering / wrapper changes)
3. ``text-tag``  - same rule + same tag + same visible text (survives attribute rewrites)

Anything left in *before* is **resolved**; anything left in *after* is **introduced**.  Every
remaining pair records which pass matched it, so the evidence of a "remaining" claim is visible.

When either scan truncated evidence for a rule (per-rule cap 50), unmatched retained findings
for that rule are **not** definitively resolved/introduced – they are ``unverified`` because the
opposite scan's omitted evidence could contain a match.  Truncated rules are marked
``indeterminate`` in ``by_rule`` and never counted as definitively fixed.
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


def _scan_stats(scan: dict[str, Any]) -> dict[str, Any]:
    """Return retained vs total counts, respecting explicit truncation metadata."""
    summary_total = int(scan.get("summary", {}).get("instances", 0))
    retained = sum(len(r["nodes"]) for r in scan.get("violations", []))
    trunc = scan.get("evidence_truncation") or {}
    omitted_meta = int(trunc.get("omitted_nodes", 0)) if isinstance(trunc, dict) else 0
    derived_omitted = summary_total - retained
    omitted = derived_omitted if derived_omitted >= 0 else omitted_meta
    if omitted < 0:
        omitted = 0
    by_rule = trunc.get("by_rule", []) if isinstance(trunc, dict) else []
    truncated = bool(trunc.get("truncated", False)) if isinstance(trunc, dict) else (omitted > 0)
    if omitted > 0:
        truncated = True
    return {
        "total": summary_total,
        "retained": retained,
        "omitted": omitted,
        "truncated": truncated,
        "by_rule": by_rule,
    }


def _rule_truncation_map(scan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return map rule_id -> {omitted, total, retained} for violations bucket."""
    trunc = scan.get("evidence_truncation") or {}
    by_rule = trunc.get("by_rule", []) if isinstance(trunc, dict) else []
    m: dict[str, dict[str, Any]] = {}
    for entry in by_rule:
        bucket = entry.get("bucket")
        if bucket not in (None, "violations"):
            continue
        rid = entry.get("id")
        if not rid:
            continue
        omitted = int(entry.get("omitted", 0))
        total = int(entry.get("total", omitted))
        m[rid] = {"omitted": omitted, "total": total, "retained": total - omitted if total >= omitted else 0}
    for r in scan.get("violations", []):
        rid = r.get("id")
        retained = len(r.get("nodes", []))
        total = int(r.get("node_count", retained))
        omitted = total - retained if total >= retained else 0
        if omitted < 0:
            omitted = 0
        if omitted > 0:
            if rid not in m:
                m[rid] = {"omitted": omitted, "total": total, "retained": retained}
            else:
                if omitted > m[rid]["omitted"]:
                    m[rid] = {"omitted": omitted, "total": total, "retained": retained}
    return m


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
    b_stats = _scan_stats(before)
    a_stats = _scan_stats(after)
    approximate = b_stats["truncated"] or a_stats["truncated"] or b_stats["omitted"] > 0 or a_stats["omitted"] > 0

    b_trunc_map = _rule_truncation_map(before)
    a_trunc_map = _rule_truncation_map(after)
    truncated_before_rules = set(b_trunc_map.keys())
    truncated_after_rules = set(a_trunc_map.keys())

    for s, name, stats in ((before, "before", b_stats), (after, "after", a_stats)):
        if stats["omitted"] > 0:
            rule_detail = ""
            if stats["by_rule"]:
                parts = [f"{r.get('id')}: {r.get('omitted')} omitted" for r in stats["by_rule"]]
                rule_detail = f" Affected rule(s): {', '.join(parts)}."
            warnings.append(
                f"The {name} scan: {stats['omitted']} finding instances were omitted from stored evidence (per-rule cap 50); total axe counts remain accurate — all findings were audited (retained {stats['retained']} of {stats['total']}). Matching is approximate and covers only retained evidence.{rule_detail} "
                "Do not interpret retained counts as complete audit totals."
            )
        elif s["summary"]["instances"] > sum(len(r["nodes"]) for r in s["violations"]):
            warnings.append(f"The {name} scan stored fewer nodes than were found (per-rule cap); counts stay accurate but matching is approximate for the overflow.")
        if s.get("blocked_requests"):
            warnings.append(f"The {name} scan blocked {len(s['blocked_requests'])} off-origin request(s); rendering may differ from production.")

    if approximate:
        warnings.append(
            "Comparison is approximate: at least one scan omitted evidence beyond the storage cap. "
            "Matched counts (resolved/remaining/introduced) reflect only definitively classifiable retained evidence; unverified findings are listed separately and omitted nodes are not claimed resolved and the comparison does not represent every affected element."
        )

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
    # Partition unmatched retained into definitive vs unverified based on opposite truncation
    resolved: list[dict[str, Any]] = []
    unverified_resolved: list[dict[str, Any]] = []
    for i in b_left:
        it = b_items[i]
        rid = it["rule_id"]
        entry = _brief(it)
        if rid in truncated_after_rules:
            entry["unverified_reason"] = f"after scan truncated for rule {rid} ({a_trunc_map[rid]['omitted']} omitted); could have match in omitted evidence"
            entry["origin"] = "before"
            entry["status"] = "unverified"
            unverified_resolved.append(entry)
        else:
            resolved.append(entry)

    introduced: list[dict[str, Any]] = []
    unverified_introduced: list[dict[str, Any]] = []
    for j in a_left:
        it = a_items[j]
        rid = it["rule_id"]
        entry = _brief(it)
        if rid in truncated_before_rules:
            entry["unverified_reason"] = f"before scan truncated for rule {rid} ({b_trunc_map[rid]['omitted']} omitted); could have existed in omitted evidence"
            entry["origin"] = "after"
            entry["status"] = "unverified"
            unverified_introduced.append(entry)
        else:
            introduced.append(entry)

    unverified = sorted(unverified_resolved + unverified_introduced, key=lambda it: (it["rule_id"], it["selector"]))
    if unverified:
        warnings.append(
            f"Unverified findings: {len(unverified_resolved)} before-retained and {len(unverified_introduced)} after-retained could not be definitively classified as resolved/introduced because the opposite scan truncated evidence for those rules ({', '.join(sorted(truncated_after_rules))} after-truncated, {', '.join(sorted(truncated_before_rules))} before-truncated). They are listed under 'unverified' and not counted as definitively resolved/introduced."
        )

    def by_rule() -> list[dict[str, Any]]:
        rules: dict[str, dict[str, Any]] = {}
        def slot(rid: str, help_text: str):
            return rules.setdefault(rid, {"rule_id": rid, "help": help_text, "before": 0, "after": 0, "before_total": 0, "after_total": 0, "before_omitted": 0, "after_omitted": 0, "before_retained": 0, "after_retained": 0})
        for it in b_items:
            slot(it["rule_id"], it["rule_help"])["before"] += 1
        for it in a_items:
            slot(it["rule_id"], it["rule_help"])["after"] += 1
        def fill_totals(scan: dict[str, Any], side: str, trunc_map: dict[str, dict[str, Any]]):
            for r in scan.get("violations", []):
                rid = r["id"]
                entry = slot(rid, r.get("help", rid))
                retained = len(r.get("nodes", []))
                total = int(r.get("node_count", retained))
                omitted = total - retained if total >= retained else 0
                if omitted < 0:
                    omitted = 0
                if side == "before":
                    entry["before_total"] = total
                    entry["before_retained"] = retained
                    entry["before_omitted"] = omitted
                    entry["before"] = retained
                else:
                    entry["after_total"] = total
                    entry["after_retained"] = retained
                    entry["after_omitted"] = omitted
                    entry["after"] = retained
            for rid, info in trunc_map.items():
                entry = rules.get(rid)
                if not entry:
                    entry = slot(rid, rid)
                if side == "before":
                    if entry.get("before_total", 0) == 0:
                        entry["before_total"] = info["total"]
                        entry["before_retained"] = info["retained"]
                        entry["before_omitted"] = info["omitted"]
                        entry["before"] = info["retained"]
                else:
                    if entry.get("after_total", 0) == 0:
                        entry["after_total"] = info["total"]
                        entry["after_retained"] = info["retained"]
                        entry["after_omitted"] = info["omitted"]
                        entry["after"] = info["retained"]
        fill_totals(before, "before", b_trunc_map)
        fill_totals(after, "after", a_trunc_map)
        for r in rules.values():
            r["delta"] = r["after"] - r["before"]
            r["delta_total"] = r.get("after_total", r["after"]) - r.get("before_total", r["before"])
            rid = r["rule_id"]
            truncated = rid in truncated_before_rules or rid in truncated_after_rules
            r["truncated"] = truncated
            if truncated:
                r["state"] = "indeterminate"
                r["definitive"] = False
            else:
                r["definitive"] = True
                if r["after"] == 0 and r["before"] > 0:
                    r["state"] = "fixed"
                elif r["before"] == 0 and r["after"] > 0:
                    r["state"] = "new"
                elif r["delta"] < 0:
                    r["state"] = "improved"
                elif r["delta"] > 0:
                    r["state"] = "worse"
                else:
                    r["state"] = "unchanged"
        return sorted(rules.values(), key=lambda r: (r["delta"], r["rule_id"]))

    by_rule_list = by_rule()

    # Base verdict from definitive findings
    if unverified and not resolved and not introduced and not remaining:
        base_verdict = "indeterminate"
    elif introduced and resolved:
        base_verdict = "mixed"
    elif introduced:
        base_verdict = "regressed"
    elif resolved:
        base_verdict = "improved"
    elif unverified:
        base_verdict = "indeterminate" if not remaining else "unchanged"
    else:
        base_verdict = "unchanged"
    # Overall verdict must not be unqualified when truncated evidence prevents definitive conclusion
    if approximate and (truncated_before_rules or truncated_after_rules):
        if base_verdict in ("unchanged", "improved", "regressed"):
            verdict = "indeterminate"
        else:
            verdict = base_verdict
    else:
        verdict = base_verdict

    sev_rank = lambda it: IMPACT_RANK.get(it["impact"], 9)  # noqa: E731
    summary = {
        "before_total": b_stats["total"],
        "after_total": a_stats["total"],
        "before_instances": b_stats["retained"],
        "after_instances": a_stats["retained"],
        "before_retained": b_stats["retained"],
        "after_retained": a_stats["retained"],
        "before_omitted": b_stats["omitted"],
        "after_omitted": a_stats["omitted"],
        "resolved": len(resolved),
        "remaining": len(remaining),
        "introduced": len(introduced),
        "unverified": len(unverified),
        "severity_changed": len(severity_changed),
        "net_change": a_stats["total"] - b_stats["total"],
        "net_change_retained": a_stats["retained"] - b_stats["retained"],
        "rules_fixed_completely": sum(1 for r in by_rule_list if r["state"] == "fixed"),
        "needs_review_before": before["summary"]["needs_review_instances"],
        "needs_review_after": after["summary"]["needs_review_instances"],
        "approximate": approximate,
        "indeterminate": len(unverified) > 0 or any(r.get("truncated") for r in by_rule_list),
    }
    return {
        "before_id": before["id"], "after_id": after["id"],
        "before_at": before["created_at"], "after_at": after["created_at"],
        "target": after["target"]["label"],
        "verdict": verdict,
        "summary": summary,
        "resolved": sorted(resolved, key=sev_rank),
        "remaining": sorted(remaining, key=sev_rank),
        "introduced": sorted(introduced, key=sev_rank),
        "unverified": sorted(unverified, key=sev_rank),
        "indeterminate_count": len(unverified),
        "indeterminate": summary["indeterminate"],
        "severity_changed": severity_changed,
        "by_rule": by_rule_list,
        "warnings": warnings,
        "approximate": approximate,
        "evidence": {
            "before": {"total": b_stats["total"], "retained": b_stats["retained"], "omitted": b_stats["omitted"], "by_rule": b_stats["by_rule"]},
            "after": {"total": a_stats["total"], "retained": a_stats["retained"], "omitted": a_stats["omitted"], "by_rule": a_stats["by_rule"]},
        },
        "caveat": ("'Resolved' means the automated check no longer fails in the rendered page for definitively classifiable retained evidence; it does not prove the fix is "
                   "semantically good (e.g. meaningful alt text) and is not a conformance claim. When evidence was truncated for a rule, unmatched retained findings for that rule are listed as 'unverified' (not definitively resolved/introduced) because omitted evidence could contain a match; rule states for truncated rules are 'indeterminate' and not counted as completely fixed."),
    }
