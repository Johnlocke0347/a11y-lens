"""``hermes a11y …`` subcommands and the ``/a11y`` slash command."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import runner, service
from .policy import PolicyError, normalize_origin
from .tools import Runtime

DEMO_DIR = Path(__file__).resolve().parent / "demo" / "broken-site"


# ---------------------------------------------------------------------------------------------
# doctor: a REAL end-to-end self-test (browser launches, axe runs, a known violation is found)
# ---------------------------------------------------------------------------------------------
def run_doctor(rt: Runtime) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    try:
        add("axe-core integrity", True, f"axe-core {runner.verify_vendored_axe()} matches vendor/VENDORED.json")
    except runner.ScanError as exc:
        add("axe-core integrity", False, str(exc))
    try:
        import playwright  # noqa: F401

        add("playwright python package", True, "importable")
    except ImportError:
        add("playwright python package", False, "missing - reinstall the plugin (hermes plugins install …) or `pip install playwright`")
    try:
        rt.store
        add("scan history database", True, str(rt.store.data_dir))
    except Exception as exc:  # noqa: BLE001
        add("scan history database", False, repr(exc))

    s = rt.settings()
    add("allowed remote origins", True, ", ".join(s.allowed_origins) or "none (loopback only)")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "index.html").write_text(
            '<!doctype html><html lang="en"><head><title>Doctor probe</title></head><body><main><h1>Probe</h1>'
            '<img src="x.png" width="10" height="10"></main></body></html>', encoding="utf-8")
        try:
            ex = runner.execute_scan(str(Path(tmp) / "index.html"), allowed_origins=[], timeout_s=30,
                                     browser_executable=s.browser_executable or None, browser_channel=s.browser_channel or None,
                                     chromium_args=s.chromium_args)
            w = ex["worker"]
            if w["status"] != "complete":
                add("browser + axe end-to-end", False, json.dumps(w.get("error") or w.get("incomplete_reasons")))
            else:
                found = [v["id"] for v in w["axe"]["violations"]]
                add("browser + axe end-to-end", "image-alt" in found,
                    f"{w['browser'].get('name')} {w['browser'].get('version')} ran axe and detected a planted missing-alt image"
                    if "image-alt" in found else f"axe ran but missed the planted violation (found: {found})")
        except Exception as exc:  # noqa: BLE001
            add("browser + axe end-to-end", False, f"{type(exc).__name__}: {exc}")
    ok = all(c["ok"] for c in checks)
    hint = "" if ok else "Fix the failing checks; if no browser is installed run: hermes a11y install"
    return {"ok": ok, "checks": checks, "hint": hint}


def _print_doctor(res: dict[str, Any]) -> None:
    for c in res["checks"]:
        print(f"[{'ok' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}")
    print("\nAll good." if res["ok"] else f"\n{res['hint']}")


# ---------------------------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------------------------
def setup_parser(parser: Any) -> None:
    sub = parser.add_subparsers(dest="a11y_cmd")
    sub.add_parser("install", help="Download Playwright's Chromium (one-time, from Playwright's official CDN)")
    sub.add_parser("doctor", help="Run a real end-to-end self-test")
    p = sub.add_parser("allow", help="Authorise a remote origin you own, e.g. https://staging.example.com")
    p.add_argument("origin")
    p = sub.add_parser("revoke", help="Remove an authorised origin")
    p.add_argument("origin")
    sub.add_parser("origins", help="List authorised origins")
    p = sub.add_parser("scan", help="Scan a URL / file / folder and print a summary")
    p.add_argument("target")
    p.add_argument("--viewport", default=None)
    p = sub.add_parser("scans", help="List scan history")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("compare", help="Compare two scans")
    p.add_argument("before")
    p.add_argument("after", nargs="?", default="latest")
    p = sub.add_parser("demo", help="Copy the bundled inaccessible demo site to a writable folder (default ./a11y-lens-demo)")
    p.add_argument("dest", nargs="?", default="a11y-lens-demo")
    p.add_argument("--reset", action="store_true", help="Overwrite an existing copy with the pristine broken site")


def make_cli_handler(rt: Runtime, ctx: Any):
    def handle(args: Any) -> int:
        cmd = getattr(args, "a11y_cmd", None)
        if cmd == "install":
            print("Downloading Chromium via `playwright install chromium` (official Playwright CDN, ~150 MB)…")
            return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])
        if cmd == "doctor":
            res = run_doctor(rt)
            _print_doctor(res)
            return 0 if res["ok"] else 1
        if cmd in ("allow", "revoke"):
            try:
                origin = normalize_origin(args.origin)
            except PolicyError as exc:
                print(str(exc))
                return 2
            cur = list(rt.settings().allowed_origins)
            if cmd == "allow" and origin not in cur:
                cur.append(origin)
            if cmd == "revoke":
                cur = [o for o in cur if o != origin]
            ctx.set_config("allowed_origins", cur)
            print(f"{'Authorised' if cmd == 'allow' else 'Revoked'} {origin}. Current: {cur or 'loopback only'}")
            print("Note: redirects to other hosts (e.g. example.com -> www.example.com) are blocked unless you authorise both.")
            return 0
        if cmd == "origins":
            print("\n".join(rt.settings().allowed_origins) or "(none - loopback only)")
            return 0
        if cmd == "scan":
            res = service.scan(rt.store, rt.settings(), args.target, viewport=args.viewport)
            print(format_scan(res))
            return 0 if res.get("ok") else 1
        if cmd == "scans":
            for s in rt.store.list(limit=args.limit):
                print(f"{s['id']}  {s['created_at']}  {s['status']:<10} rules={s['rules_violated']:<3} elements={s['instances']:<4} {s['target']}")
            return 0
        if cmd == "compare":
            res = service.compare(rt.store, args.before, args.after)
            print(format_compare(res))
            return 0 if res.get("ok") else 1
        if cmd == "demo":
            import shutil

            dest = Path(args.dest).expanduser().resolve()
            if dest.exists() and not args.reset:
                print(f"{dest} already exists (use --reset to restore the broken original).")
            else:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(DEMO_DIR, dest)
                print(f"Copied the inaccessible demo site to {dest}")
            print(f'\nTry in Hermes:\n  Audit {dest} with A11Y Lens, fix the issues in the source, rescan, and prove it improved.')
            return 0
        print("usage: hermes a11y {install|doctor|scan|scans|compare|allow|revoke|origins|demo}")
        return 0

    return handle


# ---------------------------------------------------------------------------------------------
# Human-readable formatting (slash command + CLI)
# ---------------------------------------------------------------------------------------------
def format_scan(res: dict[str, Any]) -> str:
    if not res.get("ok") and "scan_id" not in res:
        return f"✗ {res.get('message', 'Failed')}\n  {res.get('error', {}).get('message', '')}"
    lines = [f"{res['scan_id']} · {res['status'].upper()} · {res['target']}"]
    if res["status"] == "failed":
        lines.append(f"✗ {res['error']['message']}")
        return "\n".join(lines)
    s = res["summary"]
    imp = s["by_impact_elements"]
    lines.append(f"{s['rules_violated']} rules violated / {s['elements_affected']} elements "
                 f"(critical {imp['critical']}, serious {imp['serious']}, moderate {imp['moderate']}, minor {imp['minor']}); "
                 f"{s['needs_human_review_rules']} rules need human review")
    if res["status"] == "incomplete":
        lines.append("⚠ INCOMPLETE: " + "; ".join(res.get("incomplete_reasons", [])))
    if res.get("truncated") or res.get("omitted_nodes"):
        trunc = res.get("evidence_truncation", {})
        by_rule = trunc.get("by_rule", [])
        detail = ""
        if by_rule:
            detail = " Affected: " + ", ".join(f"{r.get('id')}: {r.get('omitted')} omitted" for r in by_rule) + "."
        lines.append(f"⚠ EVIDENCE TRUNCATED: {trunc.get('omitted_nodes', res.get('omitted_nodes', 0))} finding instances omitted from stored evidence (per-rule cap 50); total axe counts remain accurate ({s['elements_affected']} audited, only subset retained).{detail}")
    for f in res["findings"]:
        lines.append(f"  [{f['impact']}] {f['rule_id']} ×{f['elements_affected']} — {f['help']}")
    lines += [f"HTML report: {res['report_html']}", "Automated checks only; not a conformance claim."]
    return "\n".join(lines)


def format_compare(res: dict[str, Any]) -> str:
    if not res.get("ok"):
        return f"✗ {res['error']['message']}"
    s = res["summary"]
    # Distinguish total findings (before_total/after_total) from retained evidence (before_instances/after_instances)
    total_before = s.get("before_total", s.get("before_instances"))
    total_after = s.get("after_total", s.get("after_instances"))
    retained_before = s.get("before_retained", s.get("before_instances"))
    retained_after = s.get("after_retained", s.get("after_instances"))
    # Old consumers: before_instances/after_instances historically meant retained evidence counts – preserve that
    approx = s.get("approximate") or res.get("approximate")
    unverified = s.get("unverified", 0)
    if approx and retained_before is not None and retained_after is not None:
        lines = [f"{res['before_id']} → {res['after_id']} · {res['verdict'].upper()} (APPROXIMATE - evidence truncated)",
                 f"actual totals {total_before} → {total_after} (retained evidence {retained_before} → {retained_after} == before_instances/after_instances); resolved {s['resolved']} · remaining {s['remaining']} · newly introduced {s['introduced']} (definitive) · unverified {unverified}"]
        lines.append(f"  Note: before_instances/after_instances = retained evidence counts ({retained_before} → {retained_after}); before_total/after_total = actual axe totals ({total_before} → {total_after}). Omitted: {s.get('before_omitted',0)} → {s.get('after_omitted',0)}.")
    else:
        lines = [f"{res['before_id']} → {res['after_id']} · {res['verdict'].upper()}",
                 f"resolved {s['resolved']} · remaining {s['remaining']} · newly introduced {s['introduced']} "
                 f"(retained {retained_before} → {retained_after} == before_instances/after_instances; totals {total_before} → {total_after})"]
    for i in res["introduced"]:
        lines.append(f"  ✗ NEW [{i['impact']}] {i['rule_id']} {i['selector']}")
    if res.get("unverified"):
        for u in res["unverified"][:5]:
            lines.append(f"  ? UNVERIFIED [{u['impact']}] {u['rule_id']} {u['selector']} – {u.get('unverified_reason','')}")
        if len(res["unverified"]) > 5:
            lines.append(f"  … {len(res['unverified'])-5} more unverified in JSON report")
    for w in res["warnings"]:
        lines.append(f"  ⚠ {w}")
    lines += [f"HTML report: {res['report_html']}", res["caveat"]]
    return "\n".join(lines)


def make_slash_handler(rt: Runtime):
    from .tools import make_handlers

    handlers = make_handlers(rt)

    def slash(raw_args: str = "") -> str:
        parts = (raw_args or "").split()
        if not parts or parts[0] in ("help", "-h"):
            return ("A11Y Lens: /a11y scan <url|path> · /a11y list · /a11y report [scan-id] · /a11y compare <before> [after] · /a11y doctor")
        cmd, rest = parts[0], parts[1:]
        if cmd == "scan" and rest:
            return format_scan(json.loads(handlers["a11y_scan"]({"url": " ".join(rest)})))
        if cmd == "list":
            return "\n".join(f"{s['id']}  {s['status']:<10} rules={s['rules_violated']} elements={s['instances']}  {s['target']}"
                             for s in rt.store.list(limit=15)) or "No scans yet."
        if cmd == "report":
            r = json.loads(handlers["a11y_report"]({"scan_id": rest[0] if rest else "latest", "limit": 25}))
            if not r.get("ok"):
                return f"✗ {r['error']['message']}"
            return f"{r['scan_id']} ({r['status']}): HTML report {r['report_html']}\nJSON {r['report_json']}"
        if cmd == "compare" and rest:
            return format_compare(json.loads(handlers["a11y_compare"]({"before_id": rest[0], "after_id": rest[1] if len(rest) > 1 else "latest"})))
        if cmd == "doctor":
            res = run_doctor(rt)
            return "\n".join(f"[{'ok' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}" for c in res["checks"])
        return "Unknown subcommand. Try /a11y help"

    return slash
