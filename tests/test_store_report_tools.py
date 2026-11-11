import json
from a11y_lens import model, report, service, store as st, tools
from test_compare_unit import node, r, scan  # noqa: F401


def record(status="complete"):
    rec = model.build_record(None, error={"code": "x", "message": "y"}, target={"label": "t", "scan_url": "u", "kind": "url"})
    rec["status"] = status
    return rec


def test_store_roundtrip_ids_and_retention(tmp_path):
    s = st.Store.open_default(tmp_path)
    ids = [s.save(record(), keep=3) for _ in range(5)]
    assert ids[0] == "scan-0001" and ids[-1] == "scan-0005"
    assert s.get("scan-0001") is None and s.get(5)["id"] == "scan-0005" and s.get("scan 4") and s.get("s4")
    assert [x["id"] for x in s.list()] == ["scan-0005", "scan-0004", "scan-0003"]
    assert s.get("garbage") is None


def test_store_persists_across_connections(tmp_path):
    a = st.Store.open_default(tmp_path); a.save(record())
    b = st.Store.open_default(tmp_path)
    assert b.get(1)["id"] == "scan-0001"


def test_report_escapes_html_and_flags_failed_scan(tmp_path):
    rec = record("failed")
    rec["id"] = "scan-0001"
    rec["error"] = {"code": "x", "message": "<script>alert(1)</script>"}
    out = report.render_scan_html(rec)
    assert "<script>alert(1)</script>" not in out and "&lt;script&gt;" in out
    assert "must not be treated as a completed audit" in out
    assert "FAILED" in out and 'lang="en"' in out and "<h1>" in out


def test_report_json_has_no_screenshots():
    rec = record(); rec["screenshots"] = {"a": "AAAA"}; rec["id"] = "scan-0001"
    assert "screenshots" not in json.loads(report.render_scan_json(rec))


def test_tool_handlers_never_raise_and_return_json(tmp_path):
    rt = tools.Runtime(store=st.Store.open_default(tmp_path), settings_fn=lambda: service.Settings())
    h = tools.make_handlers(rt)
    for name, args in [("a11y_scan", {}), ("a11y_scan", {"url": "https://example.com"}), ("a11y_scan", {"url": "file:///etc/passwd"}),
                       ("a11y_scan", {"url": "/definitely/not/here"}), ("a11y_report", {"scan_id": "nope"}), ("a11y_report", {}),
                       ("a11y_compare", {}), ("a11y_compare", {"before_id": "x", "after_id": "y"}), ("a11y_scan", None)]:
        out = json.loads(h[name](args))
        assert out["ok"] is True or "error" in out, (name, args, out)
    refused = json.loads(h["a11y_scan"]({"url": "https://example.com"}))
    assert refused["refused"] and refused["error"]["code"] == "origin_not_authorised"
    assert rt.store.list() == []  # refusals are not stored as scans


def test_register_wires_everything():
    calls = {"tool": [], "cmd": [], "cli": [], "skill": []}

    class Ctx:
        def register_tool(self, **kw): calls["tool"].append(kw["name"])
        def register_command(self, name, handler, **kw): calls["cmd"].append(name)
        def register_cli_command(self, **kw): calls["cli"].append(kw["name"])
        def register_skill(self, name, path, **kw): calls["skill"].append((name, path.exists()))
        def get_config(self, key, default=None): return default
        def set_config(self, key, value): pass

    import a11y_lens
    a11y_lens.register(Ctx())
    assert calls["tool"] == ["a11y_scan", "a11y_report", "a11y_compare"]
    assert calls["cmd"] == ["a11y"] and calls["cli"] == ["a11y"] and calls["skill"] == [("a11y-repair", True)]


def test_default_retention_is_100(tmp_path):
    # B5: store default retention must align with documented/configured default of 100
    import inspect
    assert st.KEEP_DEFAULT == 100, "store.py KEEP_DEFAULT must be 100 to match plugin.yaml and docs/ARCHITECTURE.md"
    assert service.Settings().keep_scans == 100
    # Verify Store.save default param is 100
    sig = inspect.signature(st.Store.save)
    assert sig.parameters["keep"].default == 100
    # Behavioural check: saving with default keep retains 100 (not 200) - create 101 scans, oldest pruned
    s = st.Store.open_default(tmp_path / "retention")
    for i in range(101):
        rec = record()
        rec["target"]["label"] = f"t{i}"
        s.save(rec)  # default keep=100
    rows = s.list(limit=200)
    assert len(rows) == 100
    # The oldest (scan-0001) should be pruned, newest retained
    assert s.get(1) is None
    assert s.get(101) is not None
    assert s.get(101)["id"] == "scan-0101"
