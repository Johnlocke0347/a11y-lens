# A11Y Lens — demo video narration transcript

Video: `a11y-lens-demo.mp4` — 102 s, 1920×1080, 30 fps, TTS narration (piper, `lessac` voice).

| t | Narration |
|---|---|
| 0:02 | AI coding agents say they fixed your accessibility bugs. But how do you know? |
| 0:10 | A11Y Lens is a plugin for Hermes. It opens the page in a real headless Chromium, and runs the axe-core engine against the rendered DOM. |
| 0:18 | Thirty-nine violations. Not guessed — measured. Every finding carries a CSS selector, the HTML, and the reason it fails. |
| 0:27 | Every number in this report is axe-core output from an actual browser run. An empty button. Images with no alt text. Contrast eight times too low. A select with no label. |
| 0:38 | A11Y Lens never edits your code. The agent repairs the source with its normal file tools. |
| 0:46 | Adding labels, alt text, lang, a title. Fixing the role typo. Real contrast values, computed on real colors. |
| 1:02 | Now the part that matters. Re-open the page. Re-test. |
| 1:11 | Compare. Resolved. Remaining. And newly introduced — regressions the agent cannot hide. Not "trust me": the rendered page, re-tested. |
| 1:23 | It never claims WCAG compliance. A clean scan is where human testing begins. |
| 1:33 | A11Y Lens. Don't just trust the fix. Verify it. |

## On-screen captions
Captions match the narration lines above verbatim, plus one descriptive caption at 0:58 —
"The same page, after the repair."

## Suggested X post copy
> AI says it fixed your a11y bugs. A11Y Lens makes the agent prove it: real browser,
> axe-core engine, before/after regression diff. 39 violations → 1, introduced: 0 —
> measured, not claimed. #HermesAgent @NousResearch
