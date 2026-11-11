# A11Y Lens demo video — authenticity confirmation

**Video:** `a11y-lens-demo.mp4` (102 s, 1920×1080, 30 fps, H.264 + AAC narration)
**Built from:** real executions of the a11y-lens plugin against the bundled demo site, on commit `9cf8cf3` ("Fix truncated evidence comparison semantics").

## Genuinely executed and recorded (not staged)

1. **Initial scan (scan-0001).** Run through the plugin's real `execute_scan` → isolated worker
   process → Chromium **158.0.8127.18** → vendored **axe-core 4.14.0** (SHA-256 verified before the
   scan, per `runner.verify_vendored_axe`). Result: `complete`, **15 rules / 39 elements**
   (6 critical, 14 serious, 19 moderate), 21 rules passed, 2 frames audited, 24 element
   screenshots, ~4.2 s. The terminal frames in the video render the **actual tool reply JSON**
   (preserved in `tool_reply_scan1.json`); no numbers were typed by hand.
2. **Repair.** Real edits to a working copy of `demo/broken-site` (index.html, style.css). The
   diff shown on screen is the real `diff -u` output of those edits.
3. **Verification scan (scan-0002).** Same real pipeline against the repaired site: `complete`,
   **1 rule / 1 element**, 42 rules passed.
4. **Comparison.** Run through the actual `compare_scans` engine: verdict **`improved`** —
   resolved **38**, remaining **1** (`image-alt` on the iframe's inner `img`, matched by
   selector), introduced **0**, `approximate: false`, no warnings. The compare-report pages shown
   are the real `render_compare_html` output captured in Chromium.
5. **Screenshots.** All site and report imagery are real headless-Chromium captures of the demo
   site and the plugin's generated HTML reports.
6. **Narration audio.** Real text-to-speech (piper `en_US-lessac-medium`) of the transcript.

## Disclosed limitations (honest differences from a live Hermes session)

- **The Hermes Agent chat runtime was not running.** This sandbox cannot install it. The prompt
  shown at 0:10 is the documented demo prompt from `docs/DEMO.md`; the tool replies beneath it
  are the real captured outputs of the plugin's tools. In a live Hermes session the same tool
  calls return the same replies.
- **The repair edits were applied by an AI agent (the assistant) using normal file edits** —
  not by a live Hermes session. The narration ("the agent repairs the source with its normal
  file tools") is accurate as spoken; the plugin itself never edited any file.
- **Editorial assembly only.** Zoom/pan, type-on animation, captions, and cuts are editorial.
  No scan counts, findings, comparison results, or terminal values were fabricated, retyped, or
  altered anywhere in the video.
- **Sandbox-only launch flags.** The container lacks user namespaces, so the scans were run with
  `--no-sandbox --disable-gpu --disable-dev-shm-usage` passed via the plugin's operator-controlled
  `chromium_args` setting. Normal desktop use does not need these flags; the default remains `[]`.
- **No WCAG conformance claims** appear in the video; the closing card shows the plugin's real
  disclaimer ("Automated testing finds part of WCAG; not a conformance claim.").

## Environment note (potential upstream bug found while recording)

`runner._ENV_ALLOW` (stripped worker environment) includes `FONTCONFIG_PATH` but **not**
`FONTCONFIG_FILE`. In containers where fontconfig is configured via `FONTCONFIG_FILE`, the
stripped env breaks Chromium navigation (`navigation_failed: Target page, context or browser has
been closed`). Workaround used here: provide the config dir via `FONTCONFIG_PATH`. Consider
adding `FONTCONFIG_FILE` to `_ENV_ALLOW`.
