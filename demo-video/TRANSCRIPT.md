# A11Y Lens — demo video narration transcript (verified, second-accurate)

Video: `a11y-lens-demo.mp4` — 102 s, 1920×1080, 30 fps, narrated.
Captions burned into the video and `subtitles.srt` are identical and verified against the
narration audio. `[start → end]` is the exact caption window; `(voice)` is when the spoken
line actually starts in the current audio.

| # | Window | Voice | Line |
|---|--------|-------|------|
| 1 | 0:01.5 → 0:08.5 | 0:02.0 | AI coding agents say they fixed your accessibility bugs. But how do you know? |
| 2 | 0:10.0 → 0:18.5 | 0:10.5 | A11Y Lens is a plugin for Hermes. It opens the page in a real headless Chromium, and runs the axe-core engine against the rendered DOM. |
| 3 | 0:18.5 → 0:26.5 | 0:18.5 | Thirty-nine violations. Not guessed — measured. Every finding carries a CSS selector, the HTML, and the reason it fails. |
| 4 | 0:26.5 → 0:31.8 | 0:27.0 | Every number in this report is axe-core output from an actual browser run. |
| 5 | 0:31.8 → 0:34.3 | ~0:31.6 | An empty button. Images with no alt text. |
| 6 | 0:34.3 → 0:37.8 | ~0:34.1 | Contrast eight times too low. A select with no label. |
| 7 | 0:38.0 → 0:44.6 | 0:38.5 | A11Y Lens never edits your code. The agent repairs the source with its normal file tools. |
| 8 | 0:46.0 → 0:51.4 | 0:46.5 | Adding labels, alt text, lang, a title. Fixing the role typo. |
| 9 | 0:51.4 → 0:55.4 | ~0:51.2 | Real contrast values, computed on real colors. |
| 10 | 0:58.0 → 1:02.0 | — (no voice) | The same page, after the repair. |
| 11 | 1:02.0 → 1:06.5 | 1:02.5 | Now the part that matters. Re-open the page. Re-test. |
| 12 | 1:10.5 → 1:20.4 | 1:11.0 | Compare. Resolved. Remaining. And newly introduced — regressions the agent cannot hide. Not "trust me": the rendered page, re-tested. |
| 13 | 1:22.5 → 1:25.1 | 1:23.0 | It never claims WCAG compliance. |
| 14 | 1:25.1 → 1:28.5 | ~1:25.1 | A clean scan is where human testing begins. |
| 15 | 1:32.5 → 1:37.5 | 1:33.0 | A11Y Lens. Don't just trust the fix. Verify it. |

## Recording a replacement AI voice

If you re-record the narration with a better voice, generate **one clip per table row** and
place each clip so it **starts at the "Voice" timestamp** (rows 5, 6, 9, 14 are sub-sentence
splits of one spoken sentence — for those, record rows 4–6 and 8–9 as single clips starting at
0:27.0 and 0:46.5, keeping the internal pacing; the caption windows already match that pacing).
Keep total clip length ≤ the caption window. Drop the new audio over the existing track and
mute/remove the old narration.

## Suggested X post copy
> AI says it fixed your a11y bugs. A11Y Lens makes the agent prove it: real browser,
> axe-core engine, before/after regression diff. 39 violations → 1, introduced: 0 —
> measured, not claimed. #HermesAgent @NousResearch
