"""Regression tests for scan truncation and comparison semantics."""
import pytest
from a11y_lens import model
from a11y_lens.compare import CompareError, compare_scans

def node(sel, html, impact="serious", text="", tag="button"):
    return {"selector": sel, "target": [sel], "html": html, "impact": impact, "failure_summary": "", "checks": [],
            "evidence": {"tag": tag, "text": text} if text is not None else None, "has_screenshot": False,
            "fingerprint": {"selector_key": model._fp("r", sel), "html_key": model._fp("r", model.normalize_html(html))}}
def rule(rid, nodes, impact="serious"):
    return {"id": rid, "impact": impact, "help": rid, "description": "", "help_url": "", "tags": [], "wcag": {"criteria": [], "level": None, "since": None, "category": "wcag"},
            "fix_hint": None, "node_count": len(nodes), "nodes": nodes}
def r(rid, *nodes):
    for n in nodes:
        n["fingerprint"] = {"selector_key": model._fp(rid, n["selector"]), "html_key": model._fp(rid, model.normalize_html(n["html"]))}
    return rule(rid, list(nodes))
def scan(i, rules, status="complete", label="t", tags=("a",), extra=None):
    inst = sum(r["node_count"] for r in rules)
    rec = {"id": f"scan-{i:04d}", "created_at": "t", "status": status, "target": {"label": label}, "config": {"viewport": {"w": 1}, "tags": list(tags), "axe_version": "4"},
            "violations": rules, "summary": {"instances": inst, "needs_review_instances": 0}, "blocked_requests": []}
    if extra is not None:
        rec["evidence_truncation"] = extra
    else:
        retained = sum(len(r["nodes"]) for r in rules)
        omitted = inst - retained
        if omitted > 0:
            by_rule=[]
            for rr in rules:
                if rr["node_count"] > len(rr["nodes"]):
                    by_rule.append({"id": rr["id"], "omitted": rr["node_count"] - len(rr["nodes"]), "total": rr["node_count"], "bucket": "violations"})
            rec["evidence_truncation"] = {"truncated": True, "omitted_nodes": omitted, "by_rule": by_rule}
        else:
            rec["evidence_truncation"] = {"truncated": False, "omitted_nodes": 0, "by_rule": []}
    return rec
def make_worker_output(axe_violations, *, status="complete", coverage=None, evidence_truncation=None):
    coverage = coverage or {"frames_total": 1, "frames_skipped": 0}
    return {"status": status, "axe": {"violations": axe_violations, "incomplete": [], "passes": [], "inapplicable": []}, "dom_evidence": {}, "screenshots": {}, "coverage": coverage, "blocked_requests": [], "console_errors": [], "notes": [], "incomplete_reasons": [] if status=="complete" else ["frame skipped"], "evidence_truncation": evidence_truncation or {"truncated": False, "omitted_nodes": 0, "by_rule": []}, "browser": {}, "page": {}, "duration_ms": 0}
def axe_node(sel, html):
    return {"target": [sel], "html": html, "impact": "serious", "failureSummary": "", "checks": []}
def axe_rule(rid, nodes, node_count=None):
    return {"id": rid, "impact": "serious", "tags": [], "description": "desc", "help": rid, "helpUrl": "https://example.com/"+rid, "nodes": nodes, "node_count": node_count if node_count is not None else len(nodes)}
def build_record_via_model(violations, **kw):
    w = make_worker_output(violations, **kw)
    execution = {"worker": w, "resolved": {"label": kw.get("label","t"), "scan_url": "http://example/", "kind": "url", "origin": "http://example", "loopback": False}, "config": {"viewport": {"w": 1}, "tags": ["a"], "axe_version": "4", "viewport_name": "desktop", "timeout_s": 10, "settle_ms": 100, "reduced_motion": True, "color_scheme": "light", "locale": "en-US", "timezone": "UTC"}}
    return model.build_record(execution)
def test_exactly_50_no_truncation():
    nodes=[axe_node(f"#a{i}", f"<button id=a{i}></button>") for i in range(50)]
    viol=[axe_rule("image-alt", nodes)]
    rec=build_record_via_model(viol)
    assert rec["status"]=="complete"
    assert rec["evidence_truncation"]["truncated"] is False
    assert rec["evidence_truncation"]["omitted_nodes"]==0
    assert rec["summary"]["instances"]==50
def test_51_one_omitted_still_complete():
    full_nodes=[axe_node(f"#a{i}", f"<button id=a{i}></button>") for i in range(51)]
    viol_worker=[axe_rule("image-alt", full_nodes[:50], node_count=51)]
    trunc={"truncated": True, "omitted_nodes": 1, "by_rule": [{"id": "image-alt", "bucket": "violations", "omitted": 1, "total": 51}]}
    w=make_worker_output(viol_worker, evidence_truncation=trunc)
    execution={"worker": w, "resolved": {"label": "t", "scan_url": "u", "kind": "url", "origin": "o", "loopback": False}, "config": {"viewport": {"w":1}, "tags": ["a"], "axe_version":"4","viewport_name":"desktop","timeout_s":10,"settle_ms":100,"reduced_motion":True,"color_scheme":"light","locale":"en-US","timezone":"UTC"}}
    rec=model.build_record(execution)
    assert rec["status"]=="complete"
    assert rec["evidence_truncation"]["omitted_nodes"]==1
    assert rec["evidence_truncation"]["truncated"] is True
    assert rec["evidence_truncation"]["by_rule"][0]["id"]=="image-alt"
    assert rec["summary"]["instances"]==51
    assert len(rec["violations"][0]["nodes"])==50
    assert rec["incomplete_reasons"]==[]
def test_multiple_rules_exceeding_cap():
    n1=[axe_node(f"#a{i}", f"<button id=a{i}></button>") for i in range(60)]
    n2=[axe_node(f"#b{i}", f"<img id=b{i}>") for i in range(55)]
    r1=axe_rule("image-alt", n1[:50], node_count=60); r2=axe_rule("button-name", n2[:50], node_count=55)
    trunc={"truncated": True, "omitted_nodes": 15, "by_rule": [{"id": "image-alt", "omitted": 10, "total": 60, "bucket": "violations"}, {"id": "button-name", "omitted": 5, "total": 55, "bucket": "violations"}]}
    rec=build_record_via_model([r1,r2], evidence_truncation=trunc)
    assert rec["evidence_truncation"]["omitted_nodes"]==15
    assert len(rec["evidence_truncation"]["by_rule"])==2
    assert rec["summary"]["instances"]==115
    assert sum(len(r["nodes"]) for r in rec["violations"])==100
def test_accurate_total_counts_remain():
    nodes=[axe_node(f"#a{i}", f"<div id=a{i}></div>") for i in range(80)]
    rr=axe_rule("color-contrast", nodes[:50], node_count=80)
    trunc={"truncated": True, "omitted_nodes": 30, "by_rule": [{"id": "color-contrast", "omitted": 30, "total": 80, "bucket": "violations"}]}
    rec=build_record_via_model([rr], evidence_truncation=trunc)
    assert rec["summary"]["instances"]==80
    assert sum(rec["summary"]["by_impact_instances"].values())==80
def test_truncated_complete_can_be_compared():
    before_trunc=r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>") for i in range(51)])
    before_trunc["node_count"]=51; before_trunc["nodes"]=before_trunc["nodes"][:50]
    before=scan(1, [before_trunc])
    after=scan(2, [r("image-alt", node("#a0", "<img id=a0>"))])
    c=compare_scans(before, after)
    assert c["summary"]["before_total"]==51
    assert c["summary"]["before_retained"]==50
    assert c["summary"]["approximate"] is True
def test_comparison_reports_approximate():
    before_trunc=r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>") for i in range(51)])
    before_trunc["node_count"]=51; before_trunc["nodes"]=before_trunc["nodes"][:50]
    before=scan(1, [before_trunc])
    after=scan(2, [])
    c=compare_scans(before, after)
    assert c["approximate"] is True
    assert c["summary"]["approximate"] is True
    warnings_text=" ".join(c["warnings"])
    assert "approximate" in warnings_text.lower()
    assert "retained" in warnings_text.lower() or "omitted" in warnings_text.lower()
    assert "not claimed resolved" in c["caveat"] or "omitted" in c["caveat"].lower()
    assert c["summary"]["resolved"] <= c["summary"]["before_retained"]
def test_skipped_frames_remains_incomplete():
    viol=[axe_rule("image-alt", [axe_node("#a", "<img>")])]
    w=make_worker_output(viol, status="incomplete", coverage={"frames_total": 2, "frames_skipped": 1})
    w["incomplete_reasons"]=["1 of 2 frame(s) could not be audited"]
    execution={"worker": w, "resolved": {"label": "t", "scan_url": "u", "kind": "url", "origin": "o", "loopback": False}, "config": {"viewport": {"w":1}, "tags": ["a"], "axe_version":"4","viewport_name":"desktop","timeout_s":10,"settle_ms":100,"reduced_motion":True,"color_scheme":"light","locale":"en-US","timezone":"UTC"}}
    rec=model.build_record(execution)
    assert rec["status"]=="incomplete"
    good=scan(2, [])
    try:
        compare_scans(rec, good)
        assert False
    except CompareError as e:
        assert e.code=="scan_not_complete"
    try:
        compare_scans(good, rec)
        assert False
    except CompareError:
        pass
def test_failed_scans_non_comparable():
    failed=scan(1, [], status="failed")
    good=scan(2, [])
    try:
        compare_scans(good, failed)
        assert False
    except CompareError as e:
        assert e.code=="scan_not_complete"
    try:
        compare_scans(failed, good)
        assert False
    except CompareError:
        pass
def test_totals_vs_retained_distinction():
    before_trunc=r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>") for i in range(60)])
    before_trunc["node_count"]=60; before_trunc["nodes"]=before_trunc["nodes"][:50]
    after_trunc=r("image-alt", *[node(f"#b{i}", f"<img id=b{i}>") for i in range(55)])
    after_trunc["node_count"]=55; after_trunc["nodes"]=after_trunc["nodes"][:50]
    before=scan(1, [before_trunc]); after=scan(2, [after_trunc])
    c=compare_scans(before, after)
    sm=c["summary"]
    assert sm["before_total"]==60
    assert sm["before_retained"]==50
    assert sm["before_omitted"]==10
    assert sm["after_total"]==55
    assert sm["after_retained"]==50
    assert sm["after_omitted"]==5
    assert sm["net_change"]==-5
    assert sm["net_change_retained"]==0
    assert "before_total" in sm and "before_retained" in sm and "before_omitted" in sm
    assert sm["before_instances"]==sm["before_retained"]  # old semantics preserved
    assert sm["before_total"]==60
    assert sm["after_instances"]==sm["after_retained"]
    assert c["evidence"]["before"]["omitted"]==10
    assert c["evidence"]["after"]["omitted"]==5
def test_non_truncated_unchanged():
    before=scan(1, [r("button-name", node("#a", "<button id=a></button>"), node("#b", "<button id=b></button>")), r("image-alt", node("img", "<img src=x>", "critical", tag="img"))])
    after=scan(2, [r("button-name", node("#b", "<button id=b></button>")), r("label", node("#new", "<input id=new>", tag="input"))])
    c=compare_scans(before, after)
    assert c["approximate"] is False
    assert c["summary"]["approximate"] is False
    assert c["summary"]["before_total"]==3
    assert c["summary"]["after_total"]==2
    assert c["summary"]["before_retained"]==3
    assert c["summary"]["after_retained"]==2
    assert c["summary"]["before_omitted"]==0
    assert c["summary"]["after_omitted"]==0
    assert (c["summary"]["resolved"], c["summary"]["remaining"], c["summary"]["introduced"])==(2,1,1)
    assert c["verdict"]=="mixed"
    assert not any("approximate" in w.lower() and "truncat" in w.lower() for w in c["warnings"])
def test_worker_docstring_and_regex():
    import pathlib
    text=pathlib.Path('worker.py').read_text(encoding='utf-8')
    assert "Blocked requests are recorded as notes" in text
    assert "do not by themselves make the scan incomplete" in text
    assert "replace(/\\\\s+/g" in text
def test_report_contains_truncation_notice():
    from a11y_lens import report
    nodes=[axe_node(f"#a{i}", f"<button id=a{i}></button>") for i in range(60)]
    rr=axe_rule("image-alt", nodes[:50], node_count=60)
    rec=build_record_via_model([rr], evidence_truncation={"truncated": True, "omitted_nodes": 10, "by_rule": [{"id": "image-alt", "omitted": 10, "total": 60, "bucket": "violations"}]})
    rec["id"]="scan-0001"
    html=report.render_scan_html(rec)
    assert "Evidence truncated" in html
    assert "10" in html
    before_trunc=r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>") for i in range(60)])
    before_trunc["node_count"]=60; before_trunc["nodes"]=before_trunc["nodes"][:50]
    after_trunc=r("image-alt", *[node(f"#b{i}", f"<img id=b{i}>") for i in range(55)])
    after_trunc["node_count"]=55; after_trunc["nodes"]=after_trunc["nodes"][:50]
    before=scan(1, [before_trunc]); after=scan(2, [after_trunc])
    cmp=compare_scans(before, after)
    html2=report.render_compare_html(cmp)
    assert "Approximate comparison" in html2
def test_max_nodes_per_rule_unchanged():
    from a11y_lens import worker
    assert worker.MAX_NODES_PER_RULE==50

def test_before_retained_omitted_after_truncated_is_unverified():
    before = scan(1, [r("image-alt", node("#shared", "<img id=shared>", tag="img"))])
    dummy = [node(f"#x{i}", f"<img id=x{i}>", tag="img") for i in range(50)]
    shared = node("#shared", "<img id=shared>", tag="img")
    after_nodes = dummy + [shared]
    after_rule = r("image-alt", *after_nodes)
    after_rule["node_count"] = 51
    after_rule["nodes"] = after_rule["nodes"][:50]
    after = scan(2, [after_rule])
    c = compare_scans(before, after)
    assert c["summary"]["resolved"] == 0
    assert c["summary"]["unverified"] == 1
    assert len(c["unverified"]) == 1
    assert c["unverified"][0]["selector"] == "#shared"
    assert c["unverified"][0]["origin"] == "before"
    assert len(c["resolved"]) == 0
    assert c["summary"]["before_instances"] == 1
    assert c["summary"]["before_total"] == 1
    assert c["summary"]["after_instances"] == 50
    assert c["summary"]["after_total"] == 51

def test_after_retained_omitted_before_truncated_is_unverified():
    after = scan(2, [r("image-alt", node("#shared", "<img id=shared>", tag="img"))])
    dummy_before = [node(f"#y{i}", f"<img id=y{i}>", tag="img") for i in range(50)]
    shared_before = node("#shared", "<img id=shared>", tag="img")
    before_nodes = dummy_before + [shared_before]
    before_rule = r("image-alt", *before_nodes)
    before_rule["node_count"] = 51
    before_rule["nodes"] = before_rule["nodes"][:50]
    before = scan(1, [before_rule])
    c = compare_scans(before, after)
    assert c["summary"]["introduced"] == 0
    assert c["summary"]["unverified"] == 1
    assert c["unverified"][0]["selector"] == "#shared"
    assert c["unverified"][0]["origin"] == "after"
    assert len(c["introduced"]) == 0

def test_truncation_on_unrelated_rules_not_affect_unaffected():
    before2 = scan(1, [r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)]), r("button-name", node("#old", "<button id=old></button>"))])
    for rr in before2["violations"]:
        if rr["id"] == "image-alt":
            rr["node_count"] = 51
            rr["nodes"] = rr["nodes"][:50]
    before2["summary"]["instances"] = 52
    before2["evidence_truncation"] = {"truncated": True, "omitted_nodes": 1, "by_rule": [{"id": "image-alt", "omitted": 1, "total": 51, "bucket": "violations"}]}
    after3_rule = r("image-alt", *[node(f"#b{i}", f"<img id=b{i}>", tag="img") for i in range(51)])
    after3_rule["node_count"] = 51
    after3_rule["nodes"] = after3_rule["nodes"][:50]
    after3 = scan(2, [after3_rule, r("button-name", node("#old", "<button id=old></button>"))])
    after3["summary"]["instances"] = 51
    c2 = compare_scans(before2, after3)
    assert any(x["rule_id"] == "button-name" for x in c2["remaining"])
    assert not any(x["rule_id"] == "button-name" for x in c2["unverified"])

def test_truncated_rule_cannot_be_fixed():
    before_rule = r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)])
    before_rule["node_count"] = 51
    before_rule["nodes"] = before_rule["nodes"][:50]
    before = scan(1, [before_rule])
    after = scan(2, [])
    c = compare_scans(before, after)
def test_legacy_records_without_explicit_metadata():
    before_rule = r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)])
    before_rule["node_count"] = 51
    before_rule["nodes"] = before_rule["nodes"][:50]
    before = scan(1, [before_rule])
    before.pop("evidence_truncation", None)
    after = scan(2, [r("image-alt", node("#a0", "<img id=a0>", tag="img"))])
    c = compare_scans(before, after)
    assert c["summary"]["before_total"] == 51
    assert c["summary"]["before_retained"] == 50
    assert c["approximate"] is True
    assert "indeterminate" in [x["state"] for x in c["by_rule"]]

def test_cli_and_html_display_unverified():
    from a11y_lens import report
    from a11y_lens.cli import format_compare
    before = scan(1, [r("image-alt", node("#shared", "<img id=shared>", tag="img"))])
    dummy = [node(f"#x{i}", f"<img id=x{i}>", tag="img") for i in range(50)]
    shared = node("#shared", "<img id=shared>", tag="img")
    after_nodes = dummy + [shared]
    after_rule = r("image-alt", *after_nodes)
    after_rule["node_count"] = 51
    after_rule["nodes"] = after_rule["nodes"][:50]
    after = scan(2, [after_rule])
    cmp_res = compare_scans(before, after)
    cli_out = format_compare({"ok": True, "before_id": "scan-0001", "after_id": "scan-0002", "verdict": cmp_res["verdict"], "summary": cmp_res["summary"], "introduced": cmp_res["introduced"], "resolved": cmp_res["resolved"], "remaining": cmp_res["remaining"], "unverified": cmp_res["unverified"], "warnings": cmp_res["warnings"], "caveat": cmp_res["caveat"], "report_html": "/tmp/x.html", "report_json": "/tmp/x.json"})
    assert "UNVERIFIED" in cli_out
    assert "before_instances" in cli_out or "retained" in cli_out
    html = report.render_compare_html(cmp_res)
    assert "Unverified" in html
    assert "indeterminate" in html.lower() or "unverified" in html.lower()

def test_before_instances_retains_old_meaning():
    before_rule = r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)])
    before_rule["node_count"] = 51
    before_rule["nodes"] = before_rule["nodes"][:50]
    before = scan(1, [before_rule])
    after = scan(2, [])
    c = compare_scans(before, after)
    assert c["summary"]["before_instances"] == 50
    assert c["summary"]["before_retained"] == 50
    assert c["summary"]["before_total"] == 51
def test_51_before_after_50_retained_all_matched_verdict_indeterminate():
    nodes_before = [node(f"#a{i}", f"<div id=a{i}></div>") for i in range(51)]
    rule_before = r("color-contrast", *nodes_before)
    rule_before["node_count"] = 51
    rule_before["nodes"] = rule_before["nodes"][:50]
    before = scan(1, [rule_before])
    nodes_after = [node(f"#a{i}", f"<div id=a{i}></div>") for i in range(51)]
    rule_after = r("color-contrast", *nodes_after)
    rule_after["node_count"] = 51
    rule_after["nodes"] = rule_after["nodes"][:50]
    after = scan(2, [rule_after])
    c = compare_scans(before, after)
    assert c["verdict"] == "indeterminate"
    assert c["approximate"] is True
    assert c["summary"]["indeterminate"] is True
    assert len(c["remaining"]) == 50
    assert c["summary"]["resolved"] == 0
    assert c["summary"]["introduced"] == 0
    by = next(x for x in c["by_rule"] if x["rule_id"] == "color-contrast")
    assert by["state"] == "indeterminate"
    assert by["truncated"] is True
    assert c["summary"]["before_total"] == 51
    assert c["summary"]["before_instances"] == 50
    assert c["summary"]["after_total"] == 51
    assert c["summary"]["after_instances"] == 50

def test_unaffected_rules_retain_definitive():
    before = scan(1, [r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)]), r("button-name", node("#btn1", "<button id=btn1></button>"))])
    for rr in before["violations"]:
        if rr["id"] == "image-alt":
            rr["node_count"] = 51
            rr["nodes"] = rr["nodes"][:50]
    before["summary"]["instances"] = 52
    before["evidence_truncation"] = {"truncated": True, "omitted_nodes": 1, "by_rule": [{"id": "image-alt", "omitted": 1, "total": 51, "bucket": "violations"}]}
    after = scan(2, [r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)]), r("button-name", node("#btn1", "<button id=btn1></button>"))])
    for rr in after["violations"]:
        if rr["id"] == "image-alt":
            rr["node_count"] = 51
            rr["nodes"] = rr["nodes"][:50]
    after["summary"]["instances"] = 51
    after["evidence_truncation"] = {"truncated": True, "omitted_nodes": 1, "by_rule": [{"id": "image-alt", "omitted": 1, "total": 51, "bucket": "violations"}]}
    before2 = scan(1, [r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)]), r("button-name", node("#old", "<button id=old></button>"))])
    for rr in before2["violations"]:
        if rr["id"] == "image-alt":
            rr["node_count"] = 51
            rr["nodes"] = rr["nodes"][:50]
    before2["summary"]["instances"] = 52
    before2["evidence_truncation"] = {"truncated": True, "omitted_nodes": 1, "by_rule": [{"id": "image-alt", "omitted": 1, "total": 51, "bucket": "violations"}]}
    after2 = scan(2, [r("image-alt", *[node(f"#a{i}", f"<img id=a{i}>", tag="img") for i in range(51)])])
    for rr in after2["violations"]:
        if rr["id"] == "image-alt":
            rr["node_count"] = 51
            rr["nodes"] = rr["nodes"][:50]
    after2["summary"]["instances"] = 51
    after2["evidence_truncation"] = {"truncated": True, "omitted_nodes": 1, "by_rule": [{"id": "image-alt", "omitted": 1, "total": 51, "bucket": "violations"}]}
    c = compare_scans(before2, after2)
    assert any(x["rule_id"] == "button-name" and x["selector"] == "#old" for x in c["resolved"])
    assert not any(x["rule_id"] == "button-name" for x in c["unverified"])
    by_btn = next(x for x in c["by_rule"] if x["rule_id"] == "button-name")
    assert by_btn["state"] == "fixed"
def test_service_does_not_duplicate_unverified():
    from a11y_lens import service, store as st
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    s = st.Store.open_default(tmp)
    before = scan(1, [r("image-alt", node("#shared", "<img id=shared>", tag="img"))])
    before["target"] = {"label": "t", "scan_url": "http://example/", "kind": "url", "origin": "http://example", "loopback": False}
    before["config"] = {"viewport": {"w":1}, "tags": ["a"], "axe_version":"4", "viewport_name":"desktop", "timeout_s":10, "settle_ms":100, "reduced_motion":True, "color_scheme":"light", "locale":"en-US", "timezone":"UTC"}
    before["coverage"] = {"frames_total":1, "frames_skipped":0}
    before["blocked_requests"] = []
    before["console_errors"] = []
    before["notes"] = []
    before["incomplete_reasons"] = []
    before["disclaimer"] = "x"
    before["screenshots"] = {}
    before["browser"] = {}
    before["page"] = {}
    before["created_at"] = "2020-01-01T00:00:00Z"
    before["status"] = "complete"
    before["summary"] = {"instances": 1, "needs_review_instances":0, "rules_violated":1, "needs_review_rules":0, "by_impact_rules":{}, "by_impact_instances":{}, "rules_passed":0, "rules_inapplicable":0}
    before["review"] = []
    before["passes"] = []
    dummy = [node(f"#x{i}", f"<img id=x{i}>", tag="img") for i in range(50)]
    shared = node("#shared", "<img id=shared>", tag="img")
    after_nodes = dummy + [shared]
    after_rule = r("image-alt", *after_nodes)
    after_rule["node_count"] = 51
    after_rule["nodes"] = after_rule["nodes"][:50]
    after = scan(2, [after_rule])
    after["target"] = before["target"]
    after["config"] = before["config"]
    after["coverage"] = before["coverage"]
    after["blocked_requests"] = []
    after["console_errors"] = []
    after["notes"] = []
    after["incomplete_reasons"] = []
    after["disclaimer"] = "x"
    after["screenshots"] = {}
    after["browser"] = {}
    after["page"] = {}
    after["created_at"] = "2020-01-01T00:00:01Z"
    after["status"] = "complete"
    after["summary"] = {"instances": 51, "needs_review_instances":0, "rules_violated":1, "needs_review_rules":0, "by_impact_rules":{}, "by_impact_instances":{}, "rules_passed":0, "rules_inapplicable":0}
    after["review"] = []
    after["passes"] = []
    before_id = s.save(before)
    after_id = s.save(after)
    res = service.compare(s, before_id, after_id)
    assert res["ok"] is True
    assert "unverified" in res
    assert isinstance(res["unverified"], list)
    assert len(res["unverified"]) == 1
    assert res["unverified"][0]["selector"] == "#shared"
    assert res["unverified"][0]["origin"] == "before"
    assert "indeterminate" in res
    assert isinstance(res["indeterminate"], bool)
    assert res["indeterminate"] is True
    assert "indeterminate_count" in res
    assert isinstance(res["indeterminate_count"], int)
    assert res["indeterminate_count"] == 1
    assert res["indeterminate_count"] == len(res["unverified"])
    assert res["summary"]["indeterminate"] is True
    assert not isinstance(res["indeterminate"], list)



def test_existing_non_truncated_verdict_unchanged():
    before = scan(1, [r("button-name", node("#a", "<button id=a></button>"))])
    after = scan(2, [r("button-name", node("#a", "<button id=a></button>"))])
    c = compare_scans(before, after)
    assert c["verdict"] == "unchanged"
    assert c["approximate"] is False
    assert c["summary"]["indeterminate"] is False
    assert c["summary"]["before_instances"] == 1
    assert c["summary"]["before_total"] == 1

def test_scan_report_wording_finding_instances():
    from a11y_lens import report
    nodes = [axe_node(f"#a{i}", f"<button id=a{i}></button>") for i in range(60)]
    rr = axe_rule("image-alt", nodes[:50], node_count=60)
    rec = build_record_via_model([rr], evidence_truncation={"truncated": True, "omitted_nodes": 10, "by_rule": [{"id": "image-alt", "omitted": 10, "total": 60, "bucket": "violations"}]})
    rec["id"] = "scan-0001"
    html = report.render_scan_html(rec)
    assert "finding instances were omitted from stored evidence" in html
    assert "total axe counts remain accurate" in html
    assert "all findings were audited" in html.lower()

