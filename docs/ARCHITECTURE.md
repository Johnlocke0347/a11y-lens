# Architecture

```
Hermes ── a11y_scan / a11y_report / a11y_compare (tools.py, JSON in/out, never raises)
              │
           service.py ── policy.py  (URL/IP rules, DNS pinning inputs)
              │          runner.py  (local static server, worker process, hard timeout)
              │          model.py   (raw axe output → stable scan record, fingerprints)
              │          compare.py (3-pass matcher → resolved / remaining / introduced)
              │          report.py  (self-contained HTML + JSON)
              └─ store.py ── plugin_db (SQLite, survives updates) + reports/ in plugin_data_dir
                                   │
                  runner.py ──spawn──▶ worker.py (isolated process: Playwright → Chromium → axe-core)
```

## Files

| File | Role |
|---|---|
| `plugin.yaml`, `__init__.py` | Manifest + `register(ctx)`: 3 tools, `/a11y`, `hermes a11y …`, `a11y-repair` skill. `register()` does no I/O and spawns nothing. |
| `policy.py` | Decides what may be scanned. Loopback by default; remote only if a human authorised the origin; public IPs only. Returns the pinned `host → ip` map. |
| `runner.py` | Resolves local paths, serves them on `127.0.0.1:<random>`, spawns `worker.py` with a stripped env in its own process group, kills the tree on timeout, parses the sentinel-prefixed JSON result. |
| `worker.py` | Standalone script (stdlib + Playwright). Launches Chromium with `--host-resolver-rules`, route-guards every request, injects axe into all frames, collects violations, "incomplete" items, DOM evidence and element screenshots. |
| `model.py` | Normalises worker output; WCAG criterion parsing from axe tags; per-node fingerprints; fix-pattern hints for common rules. |
| `compare.py` | The regression engine. |
| `store.py` | Sequential ids (`scan-0007`), retention, report file paths. |
| `report.py` | HTML/JSON renderers. |
| `cli.py` | `hermes a11y` subcommands, `/a11y`, and `doctor` (a real end-to-end self-test). |
| `vendor/` | axe-core 4.14.0 + licence + SHA-256 manifest (verified before each scan). |

## Scan lifecycle

1. `validate_target` → resolve hostnames once, reject non-loopback unless authorised, reject non-public IPs, pin IPs.
2. Spawn worker (hard limit = page timeout + 25 s). Worker: new context (fixed locale/timezone/colour scheme/reduced motion, service workers blocked, downloads off) → `goto` → refuse HTTP ≥ 400 → verify final host is pinned → wait for load/idle (bounded) → inject axe into every frame → `axe.run` with tags `wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice`.
3. Evidence: per violating node, computed style/box/attributes, plus an element screenshot (≤ 24, password inputs skipped).
4. Parent builds a record. Status is `complete` only if the worker said so **and** axe results exist; any skipped frame, truncated node list or anything unreachable makes it `incomplete`; any error makes it `failed`. All three are stored; `a11y_compare` only accepts `complete`.

## Compare algorithm

Per violating element: `selector_key = H(rule, selector)`, `html_key = H(rule, normalised outerHTML)` (class/style/data-*/nonce stripped, whitespace collapsed), `text_key = rule|tag|visible text`. Three passes (selector → html → text-tag), each element used at most once. Leftover *before* = resolved, leftover *after* = introduced; pairs are *remaining* (with `matched_by` and severity change). Different target/viewport/rule-tags/axe-version produce warnings; incomplete/failed scans are refused.

## Storage

`plugins.plugin_storage.plugin_db("a11y-lens")` (SQLite WAL) holds one row per scan with the full record JSON; `reports/<id>.html|json` live in `plugin_data_dir`. Default retention 100 scans (`keep_scans`).

## Deliberate non-goals

Crawling, authenticated flows, form interaction, auto-patching source, WCAG "scores". Each would trade reliability or safety for demo flash.
