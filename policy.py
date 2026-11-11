"""Scan-target safety policy.

Default posture: **loopback only**.  A model can never widen it from a tool call -- extra origins are
authorised exclusively by the human through ``hermes a11y allow <origin>`` (stored in the plugin's
own settings) -- and even an authorised origin must resolve to public addresses.

Hostnames are resolved here, once, validated, and the validated IP is pinned in Chromium by the
worker (``--host-resolver-rules``).  That closes the DNS-rebinding window.

Noncanonical IP encodings (e.g. `0x7f.0.0.1`, `2130706433`) are NOT treated as IPs: Python's
`ipaddress.ip_address` only accepts canonical dotted-decimal/IPv6, so such strings fall through to
`getaddrinfo` as hostnames. Without explicit allow they are refused as
`origin_not_authorised`; even if allowed they fail closed on DNS/private-IP checks. See
`docs/SAFETY.md` § IP encodings.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urlsplit

LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


class PolicyError(Exception):
    """Target refused by policy.  ``code`` is machine-readable, ``str(e)`` is user-facing."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Target:
    url: str
    origin: str
    pinned_hosts: dict[str, str] = field(default_factory=dict)  # hostname -> validated ip
    loopback: bool = False


def normalize_origin(value: str) -> str:
    """``https://Example.com:443/path`` -> ``https://example.com``  (default ports dropped)."""
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PolicyError("bad_origin", f"Not an http(s) origin: {value!r}")
    host = parts.hostname.lower()
    port = parts.port
    default = 443 if parts.scheme == "https" else 80
    netloc = f"[{host}]" if ":" in host else host
    if port and port != default:
        netloc += f":{port}"
    return f"{parts.scheme}://{netloc}"


def _is_loopback_ip(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_loopback


def _is_public_ip(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))  # CGNAT
    )


def resolve_host(host: str) -> list[ipaddress._BaseAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PolicyError("dns_failure", f"Could not resolve {host!r}: {exc}") from exc
    out: list[ipaddress._BaseAddress] = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip not in out:
            out.append(ip)
    if not out:
        raise PolicyError("dns_failure", f"No addresses for {host!r}")
    return out


def validate_target(url: str, allowed_origins: Iterable[str] = ()) -> Target:
    """Return a pinned, validated target or raise :class:`PolicyError`."""
    if not isinstance(url, str) or not url.strip():
        raise PolicyError("bad_url", "url is required")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise PolicyError("bad_scheme", f"Only http and https targets are allowed (got {parts.scheme or 'none'!r}).")
    if parts.username or parts.password:
        raise PolicyError("credentials_in_url", "URLs containing credentials are refused; A11Y Lens never handles credentials.")
    host = (parts.hostname or "").lower()
    if not host:
        raise PolicyError("bad_url", "URL has no host")
    try:
        origin = normalize_origin(url)
    except PolicyError:
        raise
    except ValueError as exc:  # invalid port etc.
        raise PolicyError("bad_url", str(exc)) from exc

    allowed = set()
    for o in allowed_origins:
        try:
            allowed.add(normalize_origin(o))
        except PolicyError:
            continue

    # --- loopback targets: always allowed, but must truly resolve to loopback ------------------
    if host in LOOPBACK_NAMES or _literal_loopback(host):
        ip = "127.0.0.1" if host in LOOPBACK_NAMES else host
        if host in LOOPBACK_NAMES:
            ips = resolve_host(host)
            if not all(_is_loopback_ip(i) for i in ips):
                raise PolicyError("loopback_hijack", f"{host!r} resolves to a non-loopback address; refusing.")
        return Target(url=url.strip(), origin=origin, pinned_hosts={host: ip}, loopback=True)

    # --- remote targets: only human-authorised origins, only public IPs -------------------------
    if origin not in allowed:
        raise PolicyError(
            "origin_not_authorised",
            f"{origin} is not authorised. A11Y Lens only scans loopback targets by default. "
            f"If you own it, a human can run: hermes a11y allow {origin}",
        )
    ips = resolve_host(host)
    bad = [str(i) for i in ips if not _is_public_ip(i)]
    if bad:
        raise PolicyError(
            "private_address",
            f"{host!r} resolves to non-public address(es) {bad}; remote targets must be public (SSRF / rebinding guard).",
        )
    return Target(url=url.strip(), origin=origin, pinned_hosts={host: str(ips[0])}, loopback=False)


def _literal_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


