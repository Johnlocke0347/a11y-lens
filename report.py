"""Self-contained HTML reports (no network, no external fonts/scripts).  The report itself is built
to pass the checks it describes: landmarks, one h1, real headings, text labels instead of colour-only
severity, visible focus, AA contrast in light and dark mode, reduced-motion safe (no motion at all)."""

from __future__ import annotations

import html
import json
from typing import Any

from .model import IMPACT_ORDER

esc = lambda v: html.escape("" if v is None else str(v), quote=True)  # noqa: E731

CSS = """
:root{--bg:#f5f6f4;--surface:#ffffff;--ink:#16202a;--muted:#4a5663;--line:#cfd6dc;--band:#0e3b43;--band-ink:#f2f7f6;
--critical:#8c1c2b;--serious:#a3410a;--moderate:#6b5200;--minor:#1f5282;--good:#14683a;--code:#eef1f3;--focus:#0a58ca}
@media (prefers-color-scheme:dark){:root{--bg:#10161b;--surface:#18212a;--ink:#e8edf1;--muted:#aab6c1;--line:#33414e;--band:#08262b;
--band-ink:#eaf4f3;--critical:#ff9aa6;--serious:#ffb27a;--moderate:#f0cd6a;--minor:#8cc2f5;--good:#7fdc9f;--code:#0f161c;--focus:#8ab4ff}}
*{box-sizing:border-box}html{scroll-padding-top:1rem}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--focus)}:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.skip{position:absolute;left:-999px}.skip:focus{left:1rem;top:1rem;background:var(--surface);padding:.5rem 1rem;z-index:9}
header.top{background:var(--band);color:var(--band-ink);padding:2rem 1rem 1.6rem}
.wrap{max-width:62rem;margin:0 auto;padding:0 1rem}header .wrap{padding:0}
h1{font:600 1.9rem/1.2 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;margin:.2rem 0 .4rem;overflow-wrap:anywhere}
h2{font:600 1.35rem/1.25 "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;margin:2.2rem 0 .8rem}
h3{font-size:1.02rem;margin:0}
.meta{margin:0;color:inherit;opacity:.92;font-size:.95rem;overflow-wrap:anywhere}
.badge{display:inline-block;border:2px solid currentColor;border-radius:.3rem;padding:0 .5rem;font-weight:700;font-size:.85rem;margin-right:.5rem}
.notice{background:var(--surface);border:1px solid var(--line);border-left:6px solid var(--moderate);padding:.8rem 1rem;margin:1.2rem 0;border-radius:.3rem}
.notice.bad{border-left-color:var(--critical)}.notice.ok{border-left-color:var(--good)}
.counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.7rem;margin:1rem 0;padding:0;list-style:none}
.counts li{background:var(--surface);border:1px solid var(--line);border-radius:.3rem;padding:.7rem .9rem}
.counts b{display:block;font-size:2rem;line-height:1.1}.counts span{color:var(--muted);font-size:.9rem}
.c-critical b{color:var(--critical)}.c-serious b{color:var(--serious)}.c-moderate b{color:var(--moderate)}.c-minor b{color:var(--minor)}.c-good b{color:var(--good)}
details.rule{background:var(--surface);border:1px solid var(--line);border-radius:.3rem;margin:.7rem 0}
details.rule>summary{cursor:pointer;padding:.8rem 1rem;display:flex;gap:.7rem;align-items:baseline;flex-wrap:wrap}
.imp{white-space:nowrap;font-weight:700;font-size:.85rem;border:2px solid currentColor;border-radius:.3rem;padding:0 .4rem}
.imp.critical{color:var(--critical)}.imp.serious{color:var(--serious)}.imp.moderate{color:var(--moderate)}.imp.minor{color:var(--minor)}
.rid{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.88rem;color:var(--muted)}
.body{padding:0 1rem 1rem;border-top:1px solid var(--line)}
.node{border:1px solid var(--line);border-radius:.3rem;padding:.7rem .8rem;margin:.8rem 0}
pre,code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.84rem}
pre{background:var(--code);padding:.6rem .7rem;border-radius:.3rem;overflow-x:auto;margin:.4rem 0;white-space:pre-wrap;overflow-wrap:anywhere}
.sel{background:var(--code);padding:.1rem .35rem;border-radius:.25rem;overflow-wrap:anywhere}
table{border-collapse:collapse;width:100%;font-size:.9rem;margin:.4rem 0}
th,td{border-bottom:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}
.shot{max-width:100%;border:1px solid var(--line);border-radius:.3rem;background:#fff;margin:.4rem 0}
.fix{border-left:4px solid var(--good);padding:.2rem .8rem;margin:.6rem 0}
.tablewrap{overflow-x:auto}dl.kv{display:grid;grid-template-columns:max-content 1fr;gap:.2rem 1rem}dl.kv dt{color:var(--muted)}dl.kv dd{margin:0;overflow-wrap:anywhere}
footer{color:var(--muted);font-size:.88rem;margin:3rem 0 2rem}
@media(max-width:560px){h1{font-size:1.5rem}dl.kv{grid-template-columns:1fr}}
"""


def _page(title: str, header_html: str, body_html: str) -> str:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title><style>{CSS}</style></head><body>"
        f'<a class="skip" href="#main">Skip to report</a>'
        f'<header class="top"><div class="wrap">{header_html}</div></header>'
        f'<main id="main" class="wrap">{body_html}'
        f"<footer>Generated locally by A11Y Lens using axe-core. No data left this machine.</footer></main></body></html>"
    )


def _impact_chip(impact: str | None) -> str:
    i = impact or "minor"
    return f'<span class="imp {esc(i)}">{esc(i)}</span>'


def _evidence_table(node: dict[str, Any]) -> str:
    rows: list[tuple[str, str]] = []
    ev = node.get("evidence")
    if ev:
        rows += [("Element", f"<{ev['tag']}>" + (f" · text “{ev['text']}”" if ev.get("text") else "")),
                 ("Visible / focusable", f"{'yes' if ev['visible'] else 'no'} / {'yes' if ev['focusable'] else 'no'}"),
                 ("Computed", f"color {ev['style']['color']} on {ev['style']['background']}, {ev['style']['fontSize']}"),
                 ("Position (page px)", f"x {ev['box']['x']}, y {ev['box']['y']}, {ev['box']['w']}×{ev['box']['h']}")]
        if ev.get("attrs"):
            rows.append(("Relevant attributes", ", ".join(f'{k}="{v}"' for k, v in ev["attrs"].items())))
    for c in node.get("checks", []):
        data = c.get("data")
        if isinstance(data, dict) and {"contrastRatio", "fgColor", "bgColor"} <= set(data):
            rows.append(("Measured contrast",
                         f"{data['contrastRatio']}:1 (needs {data.get('expectedContrastRatio')}) — {data['fgColor']} on {data['bgColor']}"))
    if not rows:
        return ""
    body = "".join(f"<tr><th scope='row'>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)
    return f'<div class="tablewrap"><table><caption class="rid">DOM evidence captured from the rendered page</caption>{body}</table></div>'


def _rule_block(rule: dict[str, Any], shots: dict[str, str], *, open_: bool) -> str:
    w = rule["wcag"]
    sc = ", ".join(w["criteria"]) or ("best practice" if w["category"] == "best-practice" else "—")
    lvl = f" (WCAG {w['since']} level {w['level']})" if w["level"] else ""
    nodes = []
    for n in rule["nodes"]:
        shot = ""
        if n["has_screenshot"] and n["target"][0] in shots:
            shot = (f'<img class="shot" alt="Screenshot of the affected element {esc(n["selector"])}" '
                    f'src="data:image/png;base64,{shots[n["target"][0]]}">')
        fail = f"<pre>{esc(n['failure_summary'])}</pre>" if n.get("failure_summary") else ""
        nodes.append(
            f'<div class="node"><div>Selector <code class="sel">{esc(n["selector"])}</code> {_impact_chip(n.get("impact"))}</div>'
            f"<pre>{esc(n['html'])}</pre>{fail}{_evidence_table(n)}{shot}</div>"
        )
    more = ""
    if rule["node_count"] > len(rule["nodes"]):
        more = f"<p>{rule['node_count'] - len(rule['nodes'])} more affected element(s) not shown (storage cap).</p>"
    fix = f'<div class="fix"><strong>Fix pattern:</strong> {esc(rule["fix_hint"])}</div>' if rule.get("fix_hint") else ""
    return (
        f'<details class="rule"{" open" if open_ else ""}><summary>{_impact_chip(rule["impact"])}'
        f'<h3>{esc(rule["help"])}</h3><span class="rid">{esc(rule["id"])} · {rule["node_count"]} element(s) · WCAG {esc(sc)}{esc(lvl)}</span></summary>'
        f'<div class="body"><p>{esc(rule["description"])} <a href="{esc(rule["help_url"])}">Rule documentation</a></p>{fix}{"".join(nodes)}{more}</div></details>'
    )


def render_scan_html(scan: dict[str, Any]) -> str:
    s = scan["summary"]
    t = scan["target"]
    status = scan["status"]
    cls = {"complete": "ok", "incomplete": "", "failed": "bad"}[status]
    header = (
        f'<p class="meta"><span class="badge">{esc(status.upper())}</span>{esc(scan["id"])} · {esc(scan["created_at"])}</p>'
        f"<h1>Accessibility scan of {esc(t['label'])}</h1>"
        f'<p class="meta">{esc(scan["page"].get("title") or "")}</p>'
    )
    parts = [f'<div class="notice {cls}"><strong>Scope:</strong> {esc(scan["disclaimer"])}</div>']
    if status != "complete":
        why = scan.get("error", {}) or {}
        reasons = scan.get("incomplete_reasons") or []
        parts.append(
            f'<div class="notice bad" role="alert"><strong>This scan is {esc(status)}. It must not be treated as a completed audit.</strong>'
            f"<p>{esc(why.get('message', ''))}</p><ul>{''.join(f'<li>{esc(r)}</li>' for r in reasons)}</ul></div>"
        )
    if status in ("complete", "incomplete") and scan["violations"] is not None:
        imp = s["by_impact_instances"]
        parts.append("<h2>Summary</h2><ul class='counts'>" + "".join(
            f"<li class='c-{k}'><b>{imp[k]}</b><span>{k} instances</span></li>" for k in IMPACT_ORDER)
            + f"<li><b>{s['rules_violated']}</b><span>rules violated ({s['instances']} elements)</span></li>"
            + f"<li><b>{s['needs_review_rules']}</b><span>rules need human review</span></li>"
            + f"<li class='c-good'><b>{s['rules_passed']}</b><span>rules passed</span></li></ul>")
        parts.append("<h2>Violations</h2>")
        if not scan["violations"]:
            parts.append("<p>axe-core reported no automated violations for the rules in scope. This is not a conformance claim.</p>")
        for i, r in enumerate(scan["violations"]):
            parts.append(_rule_block(r, scan["screenshots"], open_=i < 3))
        if scan["review"]:
            parts.append("<h2>Needs human review</h2><p>axe-core could not decide these automatically (e.g. contrast over images). They are <strong>not</strong> counted as violations.</p>")
            for r in scan["review"]:
                parts.append(_rule_block(r, scan["screenshots"], open_=False))
        if scan["passes"]:
            parts.append("<h2>Rules that passed</h2><details><summary>Show "
                         f"{len(scan['passes'])} passed rules</summary><ul>"
                         + "".join(f"<li><code>{esc(p['id'])}</code> — {esc(p['help'])} ({p['nodes']} element(s))</li>" for p in scan["passes"])
                         + "</ul></details>")
    cfg, br = scan["config"], scan["browser"]
    kv = [("Target", t["scan_url"]), ("Viewport", f"{cfg.get('viewport_name')} ({cfg.get('viewport', {}).get('width')}×{cfg.get('viewport', {}).get('height')})"),
          ("Engine", f"axe-core {cfg.get('axe_version')}"), ("Rule tags", ", ".join(cfg.get("tags", []))),
          ("Browser", f"{br.get('name', '?')} {br.get('version', '')}"), ("Duration", f"{scan.get('duration_ms', 0)} ms"),
          ("Frames audited", f"{scan['coverage'].get('frames_total', '?')} total, {scan['coverage'].get('frames_skipped', 0)} skipped")]
    parts.append("<h2>Scan configuration</h2><dl class='kv'>" + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in kv) + "</dl>")
    for title, items in (("Notes", scan.get("notes")), ("Blocked requests", [f"{b['type']}: {b['url']}" for b in scan.get("blocked_requests", [])]),
                         ("Page console errors", scan.get("console_errors"))):
        if items:
            parts.append(f"<h2>{title}</h2><ul>{''.join(f'<li>{esc(i)}</li>' for i in items)}</ul>")
    return _page(f"A11Y Lens — {scan['id']}", header, "".join(parts))


def render_compare_html(cmp: dict[str, Any]) -> str:
    sm = cmp["summary"]
    verdict_text = {"improved": "Improved — no new violations introduced", "mixed": "Mixed — some fixed, some newly introduced",
                    "regressed": "Regressed — new violations introduced, none fixed", "unchanged": "Unchanged"}[cmp["verdict"]]
    cls = {"improved": "ok", "mixed": "", "regressed": "bad", "unchanged": ""}[cmp["verdict"]]
    header = (f'<p class="meta">{esc(cmp["before_id"])} → {esc(cmp["after_id"])}</p>'
              f"<h1>Before / after: {esc(cmp['target'])}</h1><p class='meta'>{esc(cmp['before_at'])} → {esc(cmp['after_at'])}</p>")
    parts = [f'<div class="notice {cls}"><strong>{esc(verdict_text)}.</strong> {esc(cmp["caveat"])}</div>']
    if cmp["warnings"]:
        parts.append('<div class="notice"><strong>Comparability warnings</strong><ul>' + "".join(f"<li>{esc(w)}</li>" for w in cmp["warnings"]) + "</ul></div>")
    parts.append("<h2>Summary</h2><ul class='counts'>"
                 f"<li><b>{sm['before_instances']}</b><span>violating elements before</span></li>"
                 f"<li><b>{sm['after_instances']}</b><span>violating elements after</span></li>"
                 f"<li class='c-good'><b>{sm['resolved']}</b><span>resolved</span></li>"
                 f"<li class='c-moderate'><b>{sm['remaining']}</b><span>remaining</span></li>"
                 f"<li class='c-critical'><b>{sm['introduced']}</b><span>newly introduced</span></li></ul>")

    def table(title: str, items: list[dict[str, Any]], extra: str = "") -> str:
        if not items:
            return f"<h2>{title}</h2><p>None.</p>"
        rows = "".join(
            f"<tr><td>{_impact_chip(i['impact'])}</td><td><code>{esc(i['rule_id'])}</code><br>{esc(i['help'])}</td>"
            f"<td><code class='sel'>{esc(i['selector'])}</code><pre>{esc(i['html'])}</pre></td>"
            + (f"<td>{esc(i.get('matched_by', ''))}</td>" if extra else "") + "</tr>" for i in items)
        head = "<th scope='col'>Impact</th><th scope='col'>Rule</th><th scope='col'>Element</th>" + (f"<th scope='col'>{extra}</th>" if extra else "")
        return f"<h2>{title} ({len(items)})</h2><div class='tablewrap'><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>"

    parts.append(table("Newly introduced", cmp["introduced"]))
    parts.append(table("Resolved", cmp["resolved"]))
    parts.append(table("Remaining", cmp["remaining"], "Matched by"))
    rows = "".join(f"<tr><td><code>{esc(r['rule_id'])}</code></td><td>{r['before']}</td><td>{r['after']}</td><td>{esc(r['state'])}</td></tr>" for r in cmp["by_rule"])
    parts.append("<h2>By rule</h2><div class='tablewrap'><table><thead><tr><th scope='col'>Rule</th><th scope='col'>Before</th><th scope='col'>After</th><th scope='col'>State</th></tr></thead>"
                 f"<tbody>{rows}</tbody></table></div>")
    return _page(f"A11Y Lens — {cmp['before_id']} vs {cmp['after_id']}", header, "".join(parts))


def render_scan_json(scan: dict[str, Any]) -> str:
    slim = {k: v for k, v in scan.items() if k != "screenshots"}
    return json.dumps(slim, indent=2, ensure_ascii=False)
