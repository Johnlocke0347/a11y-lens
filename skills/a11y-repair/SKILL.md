---
name: a11y-repair
description: Audit a web page for accessibility problems, fix them in source, and PROVE the fix by re-scanning the rendered page and comparing scans. Use when asked to audit, fix, or verify accessibility / WCAG / a11y.
---

# Accessibility repair loop (A11Y Lens)

You have three tools backed by a real browser and the axe-core engine. Findings come from the engine, not from you.
Never invent violations and never claim "WCAG compliant".

## Workflow

1. **Baseline.** Call `a11y_scan(url=…)`. For a local project pass the absolute path to the `.html` file or the
   folder with `index.html` (A11Y Lens serves it on loopback itself), or the dev-server URL (`http://localhost:PORT`).
   Remember the `scan_id`.
2. **Check status.** Only `status: "complete"` is a finished audit. If it is `incomplete` or `failed`, say so,
   explain why, and fix the cause (or rerun) before reporting anything.
3. **Triage.** Fix by impact: critical → serious → moderate → minor. Use `a11y_report(scan_id, rule_id=…)` for
   full evidence on a rule (selectors, HTML, measured contrast values).
4. **Repair with your normal file tools.** Edit the real source. Keep changes minimal and semantic
   (real `<label>`, `alt`, `<button>` instead of `<div role=button>`). Do not hide problems (no `aria-hidden` on
   content people need, no `display:none` tricks, no `alt=""` on meaningful images).
5. **Re-scan the same target** with the same viewport: `a11y_scan(url=…)`.
6. **Verify.** `a11y_compare(before_id=<baseline>, after_id=<new>)`. Report exactly what the tool says:
   resolved, remaining, and **newly introduced** violations. If anything was introduced, fix it and repeat.
7. **Be honest about limits.** Items under `needs_human_review` were not decided by the engine. Automated
   scans cover only part of WCAG; recommend manual keyboard / screen-reader testing before any conformance claim.

## Rules

- Never fabricate scan ids, counts or scores. Quote tool output.
- Do not authorise remote origins yourself; tell the user to run `hermes a11y allow <origin>` if a site is refused.
- Do not submit forms or interact with the page under test; A11Y Lens does not and you should not need to.
- Share the `report_html` path with the user at the end.
