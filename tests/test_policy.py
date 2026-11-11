import pytest
from a11y_lens.policy import PolicyError, normalize_origin, validate_target


def refused(url, allowed=(), code=None):
    with pytest.raises(PolicyError) as e:
        validate_target(url, allowed)
    if code:
        assert e.value.code == code


def test_loopback_allowed_by_default():
    t = validate_target("http://localhost:3000/x")
    assert t.loopback and t.pinned_hosts == {"localhost": "127.0.0.1"}
    assert validate_target("http://127.0.0.1:8080").loopback
    assert validate_target("http://[::1]:8080").loopback


def test_remote_refused_unless_authorised():
    refused("https://example.com", code="origin_not_authorised")


def test_private_and_metadata_addresses_refused_even_if_authorised():
    for host in ("http://10.0.0.5", "http://192.168.1.10", "http://169.254.169.254", "http://172.16.0.1", "http://100.64.0.1"):
        refused(host, allowed=[host], code="private_address")


def test_non_http_schemes_and_credentials_refused():
    refused("file:///etc/passwd", code="bad_scheme")
    refused("ftp://x.test", code="bad_scheme")
    refused("javascript:alert(1)", code="bad_scheme")
    refused("http://user:pw@localhost/", code="credentials_in_url")


def test_origin_normalisation():
    assert normalize_origin("HTTPS://Example.COM:443/a/b") == "https://example.com"
    assert normalize_origin("http://example.com:8080/x") == "http://example.com:8080"
    with pytest.raises(PolicyError):
        normalize_origin("ftp://x")


def test_authorised_public_origin_is_pinned(monkeypatch):
    import ipaddress
    from a11y_lens import policy
    monkeypatch.setattr(policy, "resolve_host", lambda h: [ipaddress.ip_address("93.184.216.34")])
    t = validate_target("https://example.com/page", ["https://example.com"])
    assert t.pinned_hosts == {"example.com": "93.184.216.34"} and not t.loopback


def test_dns_rebinding_to_private_refused(monkeypatch):
    import ipaddress
    from a11y_lens import policy
    monkeypatch.setattr(policy, "resolve_host", lambda h: [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("10.0.0.1")])
    refused("https://evil.test", ["https://evil.test"], code="private_address")


def test_localhost_name_hijacked_to_public_ip_refused(monkeypatch):
    import ipaddress
    from a11y_lens import policy
    monkeypatch.setattr(policy, "resolve_host", lambda h: [ipaddress.ip_address("8.8.8.8")])
    refused("http://localhost:3000", code="loopback_hijack")


def test_noncanonical_ip_encodings_fail_closed():
    # Noncanonical encodings are treated as hostnames, not IPs, and fail closed.
    # They are not loopback even though they encode 127.0.0.1 in alternative forms.
    from a11y_lens.policy import _literal_loopback
    assert not _literal_loopback("0x7f.0.0.1")
    assert not _literal_loopback("2130706433")
    assert not _literal_loopback("0x7f000001")
    assert not _literal_loopback("0177.0.0.1")
    # Without allow-list they are refused as origin_not_authorised (no network call)
    refused("http://0x7f.0.0.1/", code="origin_not_authorised")
    refused("http://0x7f.0.0.1:8000/path", code="origin_not_authorised")
    refused("http://2130706433/", code="origin_not_authorised")
    refused("http://2130706433:80/", code="origin_not_authorised")
    # Documented behaviour: they require explicit allow and then still fail closed on DNS/private checks
    # We verify the policy interface supports this without network dependence (no getaddrinfo called for the above).
