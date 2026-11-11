# Demo kit

## Prep (once, before recording)
```bash
hermes plugins install Johnlocke0347/a11y-lens --enable && hermes a11y install && hermes a11y doctor
hermes a11y demo --reset          # pristine broken site in ./a11y-lens-demo
```
Open `./a11y-lens-demo/index.html` in a browser first so viewers see a normal-looking coffee shop. Keep a terminal and a browser (for the HTML reports) side by side.

## Prompt to give Hermes
> Audit ./a11y-lens-demo with A11Y Lens. Fix the issues in the source (don't hide anything), rescan, and prove with a comparison whether it improved or broke anything.

## Expected beats (what really happens with the bundled site)
| t | On screen |
|---|---|
| 0:00 | Site looks fine. Voiceover: "Looks fine. Is it accessible?" |
| 0:08 | `a11y_scan` runs → **COMPLETE, 15 rules / 39 elements (6 critical, 14 serious, 19 moderate)** |
| 0:20 | Open the HTML report: empty button, missing alt, contrast 8×, unlabeled select, `role="buton"` typo, with selectors, HTML and screenshots |
| 0:30 | Hermes edits `index.html` / `style.css` |
| 0:50 | Second `a11y_scan` on the same folder |
| 0:58 | `a11y_compare`: resolved ~38, remaining 1 (the iframe image), **introduced 0** (numbers depend on what Hermes fixes; read them off the tool output) |
| 1:12 | Open compare report: resolved / remaining / introduced tables |
| 1:20 | Closer: "Hermes didn't say it fixed it. It re-opened the page and proved it." |

Do **not** edit numbers on screen. If Hermes introduces a regression, keep it: it is the strongest proof that the comparison is real.

## X video script (≈ 85 s)
1. **Hook (0–8 s)** "AI coding agents say they fixed your accessibility bugs. Did they? Watch me check."
2. **Scan (8–25 s)** "A11Y Lens, a Hermes plugin. Real Chromium, real axe-core. 39 violations: no labels, no alt text, unreadable contrast. Every one has a selector and evidence."
3. **Fix (25–45 s)** "Now Hermes fixes the source with its normal tools. The plugin never touches my code."
4. **Prove (45–70 s)** "Rescan. Compare. Resolved, remaining, and newly introduced. Not 'trust me': the rendered page, re-tested."
5. **Close (70–85 s)** "Loopback-only by default, forms never submitted, never claims WCAG compliance. `hermes plugins install` … A11Y Lens, built for Hermes."

Post copy: *"AI says it fixed your a11y bugs. A11Y Lens makes Hermes prove it: real browser, axe-core engine, before/after regression diff. #HermesAgent @NousResearch"*
