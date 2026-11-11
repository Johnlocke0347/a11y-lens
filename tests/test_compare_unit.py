"""Compare-engine tests on synthetic records (no browser)."""
import copy
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


def scan(i, rules, status="complete", label="t", tags=("a",)):
    inst = sum(r["node_count"] for r in rules)
    return {"id": f"scan-{i:04d}", "created_at": "t", "status": status, "target": {"label": label}, "config": {"viewport": {"w": 1}, "tags": list(tags), "axe_version": "4"},
            "violations": rules, "summary": {"instances": inst, "needs_review_instances": 0}, "blocked_requests": []}


def r(rid, *nodes):
    # rule ids differ per fingerprint, so rebuild keys with the actual rule id
    for n in nodes:
        n["fingerprint"] = {"selector_key": model._fp(rid, n["selector"]), "html_key": model._fp(rid, model.normalize_html(n["html"]))}
    return rule(rid, list(nodes))


def test_resolved_remaining_introduced():
    before = scan(1, [r("button-name", node("#a", "<button id=a></button>"), node("#b", "<button id=b></button>")), r("image-alt", node("img", "<img src=x>", "critical", tag="img"))])
    after = scan(2, [r("button-name", node("#b", "<button id=b></button>")), r("label", node("#new", "<input id=new>", tag="input"))])
    c = compare_scans(before, after)
    s = c["summary"]
    assert (s["resolved"], s["remaining"], s["introduced"]) == (2, 1, 1)
    assert c["verdict"] == "mixed"
    assert c["introduced"][0]["rule_id"] == "label"
    assert {x["rule_id"] for x in c["resolved"]} == {"button-name", "image-alt"}


def test_selector_shift_matched_by_html_not_reported_as_churn():
    before = scan(1, [r("button-name", node("body > div:nth-child(2) > button", "<button class=x>  </button>", text=""))])
    after = scan(2, [r("button-name", node("main > button", "<button class=y>  </button>", text=""))])
    c = compare_scans(before, after)
    assert (c["summary"]["resolved"], c["summary"]["introduced"], c["summary"]["remaining"]) == (0, 0, 1)
    assert c["remaining"][0]["matched_by"] == "html"
    assert c["verdict"] == "unchanged"


def test_text_tag_fallback_when_html_and_selector_change():
    before = scan(1, [r("link-name", node("a.one", '<a href="/a" class="one">Buy</a>', text="Buy", tag="a"))])
    after = scan(2, [r("link-name", node("a.two", '<a href="/b" rel="x">Buy</a>', text="Buy", tag="a"))])
    c = compare_scans(before, after)
    assert c["summary"]["remaining"] == 1 and c["remaining"][0]["matched_by"] == "text-tag"


def test_each_element_matched_once():
    same = "<button></button>"
    before = scan(1, [r("button-name", node("#a", same), node("#b", same))])
    after = scan(2, [r("button-name", node("#c", same))])
    c = compare_scans(before, after)
    assert (c["summary"]["resolved"], c["summary"]["remaining"], c["summary"]["introduced"]) == (1, 1, 0)


def test_severity_change_detected():
    before = scan(1, [r("color-contrast", node("#a", "<p id=a>x</p>", "serious", tag="p"))])
    after = scan(2, [r("color-contrast", node("#a", "<p id=a>x</p>", "minor", tag="p"))])
    c = compare_scans(before, after)
    assert c["summary"]["severity_changed"] == 1 and c["severity_changed"][0]["impact_before"] == "serious"


@pytest.mark.parametrize("bad", ["incomplete", "failed"])
def test_refuses_non_complete_scans(bad):
    good = scan(1, [])
    with pytest.raises(CompareError) as e:
        compare_scans(good, scan(2, [], status=bad))
    assert e.value.code == "scan_not_complete"
    with pytest.raises(CompareError):
        compare_scans(scan(2, [], status=bad), good)


def test_warns_on_mismatched_config():
    a, b = scan(1, []), scan(2, [], label="other", tags=("b",))
    b["config"]["viewport"] = {"w": 2}
    w = " ".join(compare_scans(a, b)["warnings"])
    assert "Different targets" in w and "viewports" in w and "tag sets" in w


def test_no_change_and_regressed_verdicts():
    x = scan(1, [r("label", node("#a", "<input id=a>", tag="input"))])
    assert compare_scans(x, copy.deepcopy(x) | {"id": "scan-0002"})["verdict"] == "unchanged"
    assert compare_scans(scan(1, []), x)["verdict"] == "regressed"


def test_wcag_tag_parsing_and_fingerprint_normalisation():
    w = model.wcag_info(["cat.color", "wcag2aa", "wcag143"])
    assert w["criteria"] == ["1.4.3"] and w["level"] == "AA" and w["since"] == "2.0"
    assert model.wcag_info(["best-practice"])["category"] == "best-practice"
    assert model.normalize_html('<a  class="x" style="a:b" data-k="1" href="/z">T</a>') == '<a href="/z">t</a>'
