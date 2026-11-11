"""A11Y Lens browser worker.

Runs in an isolated child process (spawned by ``runner.py``) so a browser crash, hang or memory
blow-up can never take Hermes down.  Reads ONE JSON job on stdin, writes ONE JSON result on stdout
(prefixed with a sentinel so stray library output cannot corrupt it).

This file is deliberately standalone (stdlib + playwright only, no imports from the plugin or from
Hermes) and never reads credentials, cookies or the user's browser profile.

Safety model
------------
* Every hostname the page may talk to is resolved ONCE by the parent, validated against the policy,
  and pinned in Chromium via ``--host-resolver-rules`` -- DNS rebinding cannot swap the IP later.
  Every other host resolves to NOTFOUND.
* A route handler additionally blocks any request whose host is not in the pinned set, which also
  covers every redirect hop.  Blocked requests are recorded as notes (the page may render differently
  than in production) but do not by themselves make the scan incomplete; only genuine coverage gaps do.
* Service workers are blocked, WebSockets are closed, downloads are refused, dialogs are dismissed,
  permissions are denied.  The worker never types into or submits anything.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any
from urllib.parse import urlsplit

SENTINEL = "A11Y_LENS_RESULT:"
MAX_NODES_PER_RULE = 50
MAX_HTML_CHARS = 700
MAX_SCREENSHOTS = 24
MAX_SCREENSHOT_BYTES = 180_000
MAX_CONSOLE = 25


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write("\n" + SENTINEL + json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _trim(text: str | None, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


# In-page helper: facts about an element that make a finding verifiable without trusting a model.
DOM_EVIDENCE_JS = """
(sel) => {
  let el = null;
  try { el = document.querySelector(sel); } catch (e) { return null; }
  if (!el) return null;
  const cs = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  const attrs = {};
  for (const a of ['id','role','aria-label','aria-labelledby','aria-hidden','alt','title','for','type','name','href','tabindex','lang']) {
    if (el.hasAttribute(a)) attrs[a] = String(el.getAttribute(a)).slice(0, 120);
  }
  const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
  return {
    tag: el.tagName.toLowerCase(),
    attrs,
    text,
    visible: !!(r.width && r.height) && cs.visibility !== 'hidden' && cs.display !== 'none',
    box: {x: Math.round(r.x + scrollX), y: Math.round(r.y + scrollY), w: Math.round(r.width), h: Math.round(r.height)},
    style: {color: cs.color, background: cs.backgroundColor, fontSize: cs.fontSize, fontWeight: cs.fontWeight},
    focusable: el.tabIndex >= 0,
  };
}
"""

AXE_RUN_JS = """
async (opts) => {
  const res = await axe.run(document, opts);
  const slimNode = (n) => ({
    target: n.target, html: n.html, impact: n.impact || null,
    failureSummary: n.failureSummary || '',
    checks: ['any','all','none'].flatMap(k => (n[k] || []).map(c => ({
      kind: k, id: c.id, impact: c.impact, message: c.message, data: c.data === undefined ? null : c.data
    }))),
  });
  const slimRule = (v) => ({
    id: v.id, impact: v.impact || null, tags: v.tags, description: v.description,
    help: v.help, helpUrl: v.helpUrl, nodes: v.nodes.map(slimNode),
  });
  return {
    version: axe.version,
    violations: res.violations.map(slimRule),
    incomplete: res.incomplete.map(slimRule),
    passes: res.passes.map(p => ({id: p.id, help: p.help, tags: p.tags, nodes: p.nodes.length})),
    inapplicable: res.inapplicable.map(p => p.id),
  };
}
"""


def run(job: dict[str, Any]) -> dict[str, Any]:
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    t0 = time.time()
    url: str = job["url"]
    timeout_ms = int(job["timeout_s"]) * 1000
    pinned: dict[str, str] = job["pinned_hosts"]  # hostname -> validated ip
    allowed_hosts = set(pinned)
    blocked: list[dict[str, str]] = []
    console_errors: list[str] = []
    notes: list[str] = []
    reasons_incomplete: list[str] = []

    result: dict[str, Any] = {
        "status": "failed",
        "error": None,
        "page": {},
        "axe": None,
        "dom_evidence": {},
        "screenshots": {},
        "coverage": {},
        "blocked_requests": blocked,
        "console_errors": console_errors,
        "notes": notes,
        "incomplete_reasons": reasons_incomplete,
        "evidence_truncation": {"omitted_nodes": 0, "by_rule": [], "truncated": False},
        "browser": {},
    }

    with open(job["axe_path"], encoding="utf-8") as fh:
        axe_source = fh.read()

    def _is_ip_literal(h: str) -> bool:
        import ipaddress

        try:
            ipaddress.ip_address(h)
            return True
        except ValueError:
            return False

    maps = [f"MAP {h} {ip}" for h, ip in pinned.items() if not _is_ip_literal(h)]
    # IP literals need no resolution; exclude them from the catch-all (route guard still checks them).
    excludes = [f"EXCLUDE {h.strip('[]')}" for h in pinned if _is_ip_literal(h)]
    # Everything not explicitly pinned resolves to NOTFOUND.
    host_rules = ", ".join(maps + ["MAP * ~NOTFOUND"] + excludes)

    args = [f"--host-resolver-rules={host_rules}", "--mute-audio", "--disable-extensions"]
    args += list(job.get("chromium_args") or [])

    with sync_playwright() as pw:
        launch_kwargs: dict[str, Any] = {"headless": True, "args": args}
        exe = job.get("browser_executable")
        channel = job.get("browser_channel")
        if exe:
            launch_kwargs["executable_path"] = exe
        elif channel:
            launch_kwargs["channel"] = channel
        browser = None
        launch_errors: list[str] = []
        attempts: list[dict[str, Any]] = [launch_kwargs]
        if not exe and not channel:
            # Managed Chromium first, then locally installed Chrome / Edge.
            attempts = [dict(launch_kwargs)] + [dict(launch_kwargs, channel=c) for c in ("chrome", "msedge")]
        for kw in attempts:
            try:
                browser = pw.chromium.launch(**kw)
                break
            except PWError as exc:  # missing browser etc.
                launch_errors.append(_trim(str(exc).splitlines()[0] if str(exc) else repr(exc), 240))
        if browser is None:
            result["error"] = {
                "code": "browser_unavailable",
                "message": "No usable Chromium/Chrome/Edge found. Run `hermes a11y install` "
                "(downloads Playwright's Chromium) or set plugins.entries.a11y-lens.settings.browser_executable.",
                "details": launch_errors,
            }
            return result

        result["browser"] = {"name": "chromium", "version": browser.version}
        context = None
        try:
            vp = job["viewport"]
            context = browser.new_context(
                viewport={"width": vp["width"], "height": vp["height"]},
                device_scale_factor=1,
                is_mobile=bool(vp.get("mobile")),
                has_touch=bool(vp.get("mobile")),
                locale="en-US",
                timezone_id="UTC",
                color_scheme="light",
                reduced_motion="reduce",
                service_workers="block",
                accept_downloads=False,
                java_script_enabled=True,
                ignore_https_errors=False,
                permissions=[],
                bypass_csp=False,
            )
            context.set_default_timeout(min(timeout_ms, 20_000))
            context.set_default_navigation_timeout(timeout_ms)

            def guard(route, request):  # noqa: ANN001
                host = _host_of(request.url)
                scheme = urlsplit(request.url).scheme
                if scheme in ("data", "blob", "about"):
                    return route.continue_()
                if scheme not in ("http", "https") or host not in allowed_hosts:
                    if len(blocked) < 200:
                        blocked.append({"url": _trim(request.url, 200), "type": request.resource_type})
                    return route.abort("blockedbyclient")
                return route.continue_()

            context.route("**/*", guard)
            try:  # WebSockets bypass route(); refuse them (older Playwright: best effort).
                context.route_web_socket("**/*", lambda ws: ws.close())
            except Exception:  # noqa: BLE001
                notes.append("WebSocket blocking unavailable on this Playwright version.")

            page = context.new_page()
            page.on("dialog", lambda d: d.dismiss())
            page.on("pageerror", lambda e: len(console_errors) < MAX_CONSOLE and console_errors.append(_trim(str(e), 240)))
            page.on(
                "console",
                lambda m: m.type == "error"
                and len(console_errors) < MAX_CONSOLE
                and console_errors.append(_trim(m.text, 240)),
            )

            try:
                response = page.goto(url, wait_until="load", timeout=timeout_ms)
            except PWTimeout:
                result["error"] = {"code": "navigation_timeout", "message": f"Page did not finish loading within {job['timeout_s']}s."}
                return result
            except PWError as exc:
                msg = str(exc).splitlines()[0] if str(exc) else repr(exc)
                code = "blocked_by_policy" if "BLOCKEDBYCLIENT" in msg.upper() else "navigation_failed"
                result["error"] = {"code": code, "message": _trim(msg, 300)}
                return result

            status_code = response.status if response else None
            if status_code is not None and status_code >= 400:
                result["error"] = {"code": "http_error", "message": f"Target answered HTTP {status_code}; refusing to audit an error page."}
                result["page"] = {"final_url": page.url, "status_code": status_code}
                return result

            final_host = _host_of(page.url)
            if final_host not in allowed_hosts:
                result["error"] = {"code": "redirected_off_origin", "message": f"Navigation ended on non-authorised host {final_host!r}."}
                return result

            try:  # let late JS settle, bounded
                page.wait_for_load_state("networkidle", timeout=min(4000, timeout_ms))
            except PWTimeout:
                notes.append("Network never went idle within 4s; audited the DOM as rendered at that moment.")
            settle = int(job.get("settle_ms", 300))
            if settle:
                page.wait_for_timeout(settle)

            result["page"] = {
                "final_url": page.url,
                "status_code": status_code,
                "title": page.title(),
                "lang": page.evaluate("document.documentElement.getAttribute('lang')"),
                "viewport": vp,
            }

            # Inject axe into every frame so iframes are audited too; track any we cannot reach.
            frames = page.frames
            skipped = 0
            for fr in frames:
                try:
                    fr.evaluate(axe_source)
                except PWError:
                    skipped += 1
            result["coverage"] = {"frames_total": len(frames), "frames_skipped": skipped}
            if skipped:
                reasons_incomplete.append(f"{skipped} of {len(frames)} frame(s) could not be audited (blocked or detached).")

            axe_opts: dict[str, Any] = {
                "resultTypes": ["violations", "incomplete", "passes", "inapplicable"],
                "runOnly": {"type": "tag", "values": job["tags"]},
            }
            try:
                axe_res = page.evaluate(AXE_RUN_JS, axe_opts)
            except PWTimeout:
                result["error"] = {"code": "axe_timeout", "message": "axe-core did not finish in time."}
                return result
            except PWError as exc:
                result["error"] = {"code": "axe_failed", "message": _trim(str(exc), 300)}
                return result

            # Trim volume, keep honest counts. Truncation does NOT make the scan incomplete:
            # audit coverage is complete; only stored evidence is capped.
            truncated = 0
            truncated_by_rule: list[dict[str, object]] = []
            for bucket in ("violations", "incomplete"):
                for rule in axe_res[bucket]:
                    rule["node_count"] = len(rule["nodes"])
                    if len(rule["nodes"]) > MAX_NODES_PER_RULE:
                        omitted = len(rule["nodes"]) - MAX_NODES_PER_RULE
                        truncated += omitted
                        truncated_by_rule.append({"id": rule["id"], "bucket": bucket, "omitted": omitted, "total": rule["node_count"]})
                        rule["nodes"] = rule["nodes"][:MAX_NODES_PER_RULE]
                    for n in rule["nodes"]:
                        n["html"] = _trim(n["html"], MAX_HTML_CHARS)
            if truncated:
                result["evidence_truncation"] = {"omitted_nodes": truncated, "by_rule": truncated_by_rule, "truncated": True}
                notes.append(f"{truncated} finding instances were omitted from stored evidence (per-rule cap {MAX_NODES_PER_RULE}); total axe counts remain accurate — all findings were audited, only a subset retained as evidence (scan remains complete).")
            else:
                result["evidence_truncation"] = {"omitted_nodes": 0, "by_rule": [], "truncated": False}
            result["axe"] = axe_res

            # DOM evidence + element screenshots for top-level targets.
            shots = 0
            for rule in axe_res["violations"]:
                for n in rule["nodes"]:
                    tgt = n["target"]
                    if len(tgt) != 1 or not isinstance(tgt[0], str):
                        continue
                    sel = tgt[0]
                    if sel in result["dom_evidence"]:
                        continue
                    try:
                        ev = page.evaluate(DOM_EVIDENCE_JS, sel)
                    except PWError:
                        ev = None
                    if not ev:
                        continue
                    result["dom_evidence"][sel] = ev
                    if shots >= MAX_SCREENSHOTS or not ev["visible"] or ev["tag"] == "html" or ev["attrs"].get("type") == "password":
                        continue
                    try:
                        loc = page.locator(sel).first
                        loc.scroll_into_view_if_needed(timeout=1500)
                        png = loc.screenshot(timeout=2500, animations="disabled")
                        if len(png) <= MAX_SCREENSHOT_BYTES:
                            import base64

                            result["screenshots"][sel] = base64.b64encode(png).decode("ascii")
                            shots += 1
                    except (PWError, PWTimeout):
                        continue

            if blocked:
                notes.append(
                    f"{len(blocked)} request(s) to non-authorised hosts were blocked; the page may render differently than in production."
                )
            result["status"] = "incomplete" if reasons_incomplete else "complete"
            return result
        except PWError as exc:
            result["error"] = {"code": "browser_error", "message": _trim(str(exc), 300)}
            return result
        finally:
            result["duration_ms"] = int((time.time() - t0) * 1000)
            try:
                if context is not None:
                    context.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    try:
        job = json.loads(sys.stdin.read())
    except (ValueError, OSError) as exc:
        _emit({"status": "failed", "error": {"code": "bad_job", "message": str(exc)}})
        return 2
    try:
        res = run(job)
    except ImportError as exc:
        res = {"status": "failed", "error": {"code": "playwright_missing", "message": f"Playwright is not installed: {exc}"}}
    except Exception as exc:  # noqa: BLE001 - last-resort, never crash silently
        res = {"status": "failed", "error": {"code": "worker_crash", "message": _trim(repr(exc), 300)}}
    _emit(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
