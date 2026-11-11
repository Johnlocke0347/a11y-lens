"""Real Chromium + real axe-core.  Nothing here is mocked."""
import http.server
import json
import re
import socket
import threading
from pathlib import Path

import pytest
from a11y_lens import service

EXPECTED_BROKEN_RULES = {"button-name", "image-alt", "color-contrast", "select-name", "html-has-lang", "document-title",
                         "link-name", "frame-title", "heading-order", "aria-roles", "tabindex"}


def scan(store, settings, target, **kw):
    return service.scan(store, settings, str(target), **kw)


def rules_of(res):
    return {f["rule_id"] for f in res["findings"]}


def test_broken_site_real_violations_detected(store, settings, demo):
    broken, _ = demo
    res = scan(store, settings, broken / "index.html")
    assert res["status"] == "complete" and res["ok"]
    full = service.report(store, res["scan_id"], limit=25)
    found = {r["id"] for r in full["violations"]}
    assert EXPECTED_BROKEN_RULES <= found, EXPECTED_BROKEN_RULES - found
    assert res["summary"]["elements_affected"] >= 20
    # evidence is real: contrast measurements come from the engine
    cc = next(r for r in full["violations"] if r["id"] == "color-contrast")
    data = [c["data"] for n in cc["nodes"] for c in n["checks"] if "data" in c]
    assert data and all(float(d["contrastRatio"]) < float(str(d["expectedContrastRatio"]).split(":")[0]) for d in data)
    # the planted empty button is reported with its real selector
    bn = next(r for r in full["violations"] if r["id"] == "button-name")
    assert any("button" in n["selector"] for n in bn["nodes"])
    assert Path(res["report_html"]).read_text(encoding="utf-8").count("<details") >= 5
    assert json.loads(Path(res["report_json"]).read_text(encoding="utf-8"))["status"] == "complete"


def test_scan_is_reproducible(store, settings, demo):
    broken, _ = demo
    a = scan(store, settings, broken / "index.html")
    b = scan(store, settings, broken / "index.html")
    ra = {(r["id"], r["node_count"]) for r in service.report(store, a["scan_id"], limit=25)["violations"]}
    rb = {(r["id"], r["node_count"]) for r in service.report(store, b["scan_id"], limit=25)["violations"]}
    assert ra == rb
    c = service.compare(store, a["scan_id"], b["scan_id"])
    assert c["verdict"] == "unchanged" and c["summary"]["resolved"] == 0 and c["summary"]["introduced"] == 0


def test_repair_loop_resolves_and_remaining_is_honest(store, settings, demo):
    broken, fixed = demo
    before = scan(store, settings, broken / "index.html")
    after = scan(store, settings, fixed / "index.html")
    # same label required for apples-to-apples; different dirs => warning, still computed
    c = service.compare(store, before["scan_id"], after["scan_id"])
    assert c["ok"] and c["summary"]["resolved"] >= 30 and c["summary"]["introduced"] == 0
    assert c["verdict"] == "improved"
    assert any("Different targets" in w for w in c["warnings"])
    # the iframe's missing alt is NOT fixed in the reference -> reported as remaining, not hidden
    assert [x["rule_id"] for x in c["remaining"]] == ["image-alt"]
    assert c["summary"]["after_instances"] == 1


def test_in_place_repair_same_target_then_regression(store, settings, demo):
    """The real demo flow: scan, edit the SAME file, rescan, compare; then break something new."""
    broken, _ = demo
    page = broken / "index.html"
    s1 = scan(store, settings, page)
    html = page.read_text()
    html = html.replace("<html>", '<html lang="en">').replace("<head>", "<head>\n<title>Lumen</title>")
    html = html.replace('<img src="hero.svg" width="520" height="220">', '<img src="hero.svg" width="520" height="220" alt="Roasted beans">')
    page.write_text(html)
    s2 = scan(store, settings, page)
    c = service.compare(store, s1["scan_id"], s2["scan_id"])
    assert not c["warnings"]
    fixed_rules = {r["rule_id"] for r in c["by_rule"] if r["state"] == "fixed"}
    assert {"html-has-lang", "document-title"} <= fixed_rules
    assert c["summary"]["introduced"] == 0 and c["summary"]["resolved"] >= 3 and c["verdict"] == "improved"
    # now introduce a regression: new image without alt + new unlabeled button
    html = page.read_text().replace("</body>", '<img src="pin.svg" width="20" height="20"><button></button></body>')
    page.write_text(html)
    s3 = scan(store, settings, page)
    c2 = service.compare(store, s2["scan_id"], s3["scan_id"])
    assert c2["summary"]["resolved"] == 0 and c2["verdict"] == "regressed"
    # axe also flags the new content for sitting outside any landmark (`region`); that is a real new finding
    assert {"image-alt", "button-name"} <= {i["rule_id"] for i in c2["introduced"]}
    assert c2["summary"]["introduced"] == len(c2["introduced"]) >= 2
    # 'previous' resolves to the last complete scan of the same target
    c3 = service.compare(store, "previous", "latest")
    assert c3["before_id"] == s2["scan_id"] and c3["after_id"] == s3["scan_id"]
    assert "regress" in Path(c2["report_html"]).read_text().lower()


def test_review_items_not_counted_as_violations(store, settings, tmp_path):
    p = tmp_path / "proj"; p.mkdir()
    (p / "index.html").write_text('<!doctype html><html lang="en"><head><title>t</title></head><body><main><h1>x</h1>'
                                  '<div style="background:linear-gradient(#fff,#000);color:#888;padding:20px">Text over gradient</div></main></body></html>')
    res = scan(store, settings, p / "index.html")
    assert res["status"] == "complete"
    assert "color-contrast" not in rules_of(res)
    assert any(r["rule_id"] == "color-contrast" for r in res["needs_human_review"])


# ---------------------------------------------------------------- failure and safety boundaries
class _Srv:
    def __init__(self, handler):
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def close(self):
        self.srv.shutdown(); self.srv.server_close()


def handler_factory(routes):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            r = routes.get(self.path)
            if r is None:
                self.send_response(404); self.end_headers(); self.wfile.write(b"nope"); return
            r(self)
    return H


def html(body):
    def _r(h):
        h.send_response(200); h.send_header("Content-Type", "text/html"); h.end_headers(); h.wfile.write(body.encode())
    return _r


def test_http_404_is_failed_not_complete(store, settings):
    s = _Srv(handler_factory({}))
    try:
        res = scan(store, settings, f"http://127.0.0.1:{s.port}/missing")
    finally:
        s.close()
    assert res["status"] == "failed" and res["error"]["code"] == "http_error" and not res["ok"]
    assert "findings" not in res and "FAILED" in res["message"]
    assert service.compare(store, res["scan_id"], res["scan_id"])["error"]["code"] == "scan_not_complete"


def test_redirect_off_origin_is_blocked(store, settings):
    def redirect(h):
        h.send_response(302); h.send_header("Location", "http://127.0.0.2:9/"); h.end_headers()
    s = _Srv(handler_factory({"/": redirect}))
    try:
        res = scan(store, settings, f"http://127.0.0.1:{s.port}/")
    finally:
        s.close()
    assert res["status"] == "failed" and res["error"]["code"] in ("blocked_by_policy", "navigation_failed", "redirected_off_origin")


def test_offorigin_subresources_blocked_and_disclosed(store, settings):
    page = '<!doctype html><html lang="en"><head><title>t</title></head><body><main><h1>x</h1><img src="http://example.invalid/a.png" alt="a"></main></body></html>'
    s = _Srv(handler_factory({"/": html(page)}))
    try:
        res = scan(store, settings, f"http://127.0.0.1:{s.port}/")
    finally:
        s.close()
    assert res["status"] == "complete" and any("blocked" in w for w in res["warnings"])
    full = service.report(store, res["scan_id"])
    assert full["blocked_requests"] and "example.invalid" in full["blocked_requests"][0]["url"]


def test_hung_server_times_out_as_failed(store, settings):
    lsock = socket.socket(); lsock.bind(("127.0.0.1", 0)); lsock.listen(5)
    port = lsock.getsockname()[1]
    try:
        res = scan(store, settings, f"http://127.0.0.1:{port}/", timeout_s=5)
    finally:
        lsock.close()
    assert res["status"] == "failed" and res["error"]["code"] in ("navigation_timeout", "scan_timeout")


def test_dialogs_and_downloads_do_not_hang_or_act(store, settings):
    page = ('<!doctype html><html lang="en"><head><title>t</title></head><body><main><h1>x</h1>'
            '<script>alert("hi");confirm("sure?");</script><form action="/submit" method="post"><input type="text" aria-label="n"></form></main></body></html>')
    hits = []
    def submit(h): hits.append(1); html("ok")(h)
    s = _Srv(handler_factory({"/": html(page), "/submit": submit}))
    try:
        res = scan(store, settings, f"http://127.0.0.1:{s.port}/")
    finally:
        s.close()
    assert res["status"] == "complete" and hits == []  # forms are never submitted


def test_worker_crash_surfaces_as_failed_scan(store, settings, monkeypatch):
    from a11y_lens import runner
    monkeypatch.setattr(runner, "WORKER_PATH", Path(__file__).parent / "_crash_worker.py")
    (Path(__file__).parent / "_crash_worker.py").write_text("import sys,os\nsys.stdout.write('garbage')\nos._exit(7)\n")
    try:
        res = scan(store, settings, Path(__file__).parents[1] / "demo" / "fixed-reference" / "index.html")
    finally:
        (Path(__file__).parent / "_crash_worker.py").unlink(missing_ok=True)
    assert res["status"] == "failed" and res["error"]["code"] == "worker_crash"
    assert store.get(res["scan_id"])["status"] == "failed"


def test_worker_environment_has_no_secrets(monkeypatch):
    from a11y_lens import runner
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret"); monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret2")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    env = runner._clean_env()
    assert not any("KEY" in k or "TOKEN" in k or "SECRET" in k for k in env)


def test_missing_browser_gives_actionable_error(store, tmp_path):
    p = tmp_path / "proj"; p.mkdir(); (p / "index.html").write_text("<html><body>x</body></html>")
    res = service.scan(store, service.Settings(browser_executable="/nonexistent/chrome"), str(p / "index.html"))
    assert res["status"] == "failed" and res["error"]["code"] == "browser_unavailable"
    assert "hermes a11y install" in res["error"]["message"]
