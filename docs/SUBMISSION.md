# Submission checklist

1. Create the public repo (`Johnlocke0347/a11y-lens`), push this directory as the repo root, replace `Johnlocke0347` in `plugin.yaml` (`homepage`) and `README.md`.
2. `pytest -q` and `hermes plugins validate .` must be green on your machine.
3. Record the demo (see `DEMO.md`), post it on X tagging @NousResearch with the hackathon tag.
4. Pin the commit: `git rev-parse HEAD` → `sha` below.
5. Fork `NousResearch/hermes-agent`, add `plugin-catalog/a11y-lens.yaml`, open the PR with the description below. Confirm the hackathon's own submission rules and deadline on the official announcement.

## `plugin-catalog/a11y-lens.yaml`
```yaml
name: a11y-lens
repo: https://github.com/Johnlocke0347/a11y-lens
sha: <40-hex commit sha>
description: >-
  Autonomous website accessibility testing and repair verification. Scans pages in a real headless
  Chromium with the axe-core engine, stores evidence-backed scans, and compares before/after scans
  (resolved / remaining / newly introduced) so Hermes can prove its fixes in the rendered page.
  Disclosure: launches a local headless Chromium (Playwright) in an isolated subprocess; network access is
  limited to loopback and origins a human authorises with `hermes a11y allow`; `hermes a11y install`
  downloads Playwright's Chromium from Playwright's official CDN on explicit user command; serves a
  user-supplied local .html folder on 127.0.0.1 for the duration of a scan; stores scan history and
  reports locally via plugin storage; never submits forms, collects credentials or sends data off-machine.
maintainer: Johnlocke0347
tier: community
category: web
requires_hermes: ">=0.23.0"
docs_url: https://github.com/Johnlocke0347/a11y-lens#readme
version: "0.1.0"
platforms: []
capabilities:
  provides_tools: [a11y_scan, a11y_report, a11y_compare]
  provides_hooks: []
  provides_middleware: []
  requires_env: []
```

## PR description
**A11Y Lens** gives Hermes a verified accessibility repair loop: `a11y_scan` (real Chromium + axe-core 4.14.0 on the rendered DOM), `a11y_report` (stored evidence), `a11y_compare` (resolved / remaining / introduced, matched by selector → normalised HTML → tag+text). It also registers `/a11y`, `hermes a11y …` and a bundled `a11y-repair` skill.

**Hermes surfaces used:** `register_tool` ×3, `register_command`, `register_cli_command`, `register_skill`, `config_schema`, `plugin_db`/`plugin_data_dir`. No hooks, middleware, core overrides, or env vars.

**Rule 13 disclosure:** spawns a local headless Chromium (Playwright) in a separate process with a stripped environment and a hard timeout; contacts only loopback and human-authorised origins (DNS pinned, redirects/sub-resources to other hosts blocked and reported); `hermes a11y install` runs `playwright install chromium` only when the user invokes it; local-folder mode serves the page's own folder on 127.0.0.1 during a scan (html-only, symlink/`..` guarded, refuses `/`, `$HOME`, system dirs); all data stays local; forms are never submitted; no credentials handled.

**Rule 3 / 17:** no self-update, no bundled binaries. `vendor/axe.min.js` is axe-core 4.14.0 (MPL-2.0) re-printed with line breaks only (no compress/mangle) so line-based scanners don't match across one 650 KB line; hashes and the reproduce command are in `vendor/VENDORED.json`, and the file is hash-verified before every scan. Scanner output: no `dangerous`; medium-only findings from the minified JS and `subprocess` use.

**Tests:** 42 (policy/SSRF, compare engine, store, reports, plus real-browser scans, redirects, timeouts, crashes, non-submission). `hermes plugins validate` passes locally.
