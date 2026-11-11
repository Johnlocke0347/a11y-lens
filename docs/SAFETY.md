# Safety model

| Threat | Mitigation | Test |
|---|---|---|
| Model scans internal/cloud-metadata hosts (SSRF) | Loopback only by default; remote origins need `hermes a11y allow` by a human; non-public IPs (RFC1918, link-local/169.254.*, CGNAT, loopback, multicast, reserved) refused even for authorised origins | `test_policy.py` |
| DNS rebinding | Resolve once, validate all A/AAAA records, pin the IP in Chromium via `--host-resolver-rules`; everything else → NOTFOUND | `test_dns_rebinding_to_private_refused`, `test_localhost_name_hijacked_to_public_ip_refused` |
| Redirect to a forbidden host | Route guard sees every hop; final host re-checked | `test_redirect_off_origin_is_blocked` |
| Page pulls third-party resources | Only pinned hosts may be contacted; blocked requests are recorded and shown in the report | `test_offorigin_subresources_blocked_and_disclosed` |
| `file://`, `javascript:`, credentials in URL | Refused by scheme / userinfo checks | `test_non_http_schemes_and_credentials_refused` |
| Local mode serves secrets | Only `.html/.htm` targets or a folder with `index.html`; symlink and `..` escapes blocked; refuses `/`, `$HOME`, top-level system dirs | `test_static_server_serves_dir_and_blocks_escape`, `test_local_serving_refuses_dangerous_targets` |
| Malicious page affects the host | Worker is a separate process, stripped env, killed as a process group on timeout; service workers blocked, WebSockets closed, downloads refused, dialogs dismissed, no permissions | `test_worker_environment_has_no_secrets`, `test_hung_server_times_out_as_failed`, `test_worker_crash_surfaces_as_failed_scan` |
| Destructive interaction | The worker never clicks, types or submits; | `test_dialogs_and_downloads_do_not_hang_or_act` (asserts a form endpoint is never hit) |
| Credential collection | No cookies/profile; password inputs never screenshotted; no credentials in URLs | policy tests |
| Tampered engine | SHA-256 of `vendor/axe.min.js` checked before every scan | `test_axe_integrity_check_detects_tampering` |
| Incomplete result mistaken for an audit | `complete / incomplete / failed`; compare refuses non-complete; report banners | `test_http_404_is_failed_not_complete`, `test_refuses_non_complete_scans` |
| Noncanonical IP encodings | Treated as hostnames, not IPs; require explicit allow and DNS resolution — fail closed (see below) | `test_noncanonical_ip_encodings_fail_closed` |

## Chromium configuration

- `chromium_args` in `plugin.yaml` / Settings are **operator-controlled only** (inherited from the host config, never from a model tool call). The worker passes them verbatim to Playwright's `launch`.
- Dangerous flags weaken browser isolation and must not be used on untrusted content: `--no-sandbox` disables Chromium's sandbox, `--disable-setuid-sandbox`, `--disable-dev-shm-usage` change sandboxing/memory isolation, and `--disable-web-security` / `--disable-site-isolation-trials` disable same-origin protections. Only add flags you understand; the default is an empty list and that is the secure default.
- Do not change browser defaults in code to include weak flags; keep `chromium_args` defaulting to `[]`.

## IP encodings

Noncanonical IP representations (e.g. `0x7f.0.0.1`, `2130706433`, `0x7f000001`, octal `0177.0.0.1`) are **not parsed as IP addresses** by the Python `ipaddress` module used in `policy.py`. They are handled as hostnames: they must be explicitly authorised via `hermes a11y allow` like any remote host, and hostname resolution is performed via `getaddrinfo`. Because they do not resolve to a validated public IP (or fail DNS), the request is refused — **fail closed**. This avoids SSRF bypasses via alternative IP encodings without introducing custom parsers.

## Screenshot storage

Screenshots are per-element PNGs (≤180 000 bytes each, ≤24 per scan, base64-encoded in the scan record) stored together with the scan JSON in SQLite (`data.db` WAL). Retention (`keep_scans`, default 100) bounds total DB size: worst-case ≈ 24×180 kB ≈ 4.3 MiB raw (≈5.7 MiB base64) per scan, so 100 scans ≈ 570 MiB upper bound; typical scans use far less (most elements are invisible or skipped). The limit is intentional — do not silently discard evidence. If DB growth is a concern, lower `keep_scans` via host config; do not redesign the DB for this remediation. Reports (`reports/<id>.html|json`) contain embedded images from the same bounded set.

## Known limits (honest)

- Pinning protects the page's *own* authorised hosts. It is not a general network sandbox: a malicious *authorised* site still runs JavaScript in Chromium. Only authorise origins you own.
- Chromium may be launched with `--no-sandbox` by Playwright defaults inside containers; run Hermes in a container/VM if you scan untrusted pages.
- DNS pinning is per scan; long-lived pages are out of scope (scans are bounded to ≤120 s).

