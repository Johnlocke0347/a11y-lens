
from pathlib import Path
import urllib.error
import urllib.request

import pytest
from a11y_lens import runner


def test_static_server_serves_dir_and_blocks_path_escape(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "secret.txt").write_text("TOP SECRET")

    with runner.serve_directory(root) as base:
        assert b"hi" in urllib.request.urlopen(base + "/index.html").read()

        for bad in ("/../secret.txt", "/%2e%2e/secret.txt"):
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(base + bad)

        assert base.startswith("http://127.0.0.1:")


def test_static_server_blocks_symlink_escape(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text("<h1>hi</h1>")
    (tmp_path / "secret.txt").write_text("TOP SECRET")

    link = root / "link"
    try:
        link.symlink_to(tmp_path / "secret.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation unavailable on this system: {exc}")

    with runner.serve_directory(root) as base:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/link")


def test_axe_integrity_check_detects_tampering(tmp_path, monkeypatch):
    assert runner.verify_vendored_axe() == "4.14.0"
    fake = tmp_path / "axe.min.js"
    fake.write_text("evil()")
    monkeypatch.setattr(runner, "AXE_PATH", fake)

    with pytest.raises(runner.ScanError) as e:
        runner.verify_vendored_axe()
    assert e.value.code == "axe_tampered"


def test_viewport_parsing():
    assert runner.parse_viewport(None)[0] == "desktop"
    assert runner.parse_viewport("mobile")[1]["mobile"] is True
    assert runner.parse_viewport("800x600")[1]["width"] == 800

    with pytest.raises(runner.ScanError):
        runner.parse_viewport("999999x1")


def test_classify_input(tmp_path):
    f = tmp_path / "a.html"
    f.write_text("x")

    assert runner.classify_input(str(f))[0] == "local"
    assert runner.classify_input("http://localhost:1")[0] == "url"

    with pytest.raises(runner.ScanError):
        runner.classify_input(str(tmp_path / "nope.html"))


def test_local_serving_refuses_dangerous_targets(tmp_path):
    for bad in ("/etc/passwd", "/", str(Path.home()), "/etc/hosts", "/usr"):
        if Path(bad).exists():
            with pytest.raises(runner.ScanError) as e:
                runner.classify_input(bad)
            assert e.value.code in ("not_html", "unsafe_root"), bad

    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "x.txt").write_text("x")

    with pytest.raises(runner.ScanError):
        runner.classify_input(str(tmp_path / "a" / "b" / "x.txt"))

def test_worker_handles_invalid_utf8_output(tmp_path, monkeypatch):
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import sys\n"
        "sys.stderr.buffer.write(bytes([0xB7]))\n"
        "sys.stdout.buffer.write(bytes([0xB7]) + "
        "b'\\nA11Y_LENS_RESULT:{\"status\":\"ok\"}\\n')\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "WORKER_PATH", worker)

    result = runner.run_worker({}, hard_timeout_s=5)
    assert result == {"status": "ok"}


def test_worker_invalid_utf8_without_result_is_controlled_crash(
    tmp_path, monkeypatch
):
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import sys\n"
        "sys.stdout.buffer.write(bytes([0xB7]))\n"
        "sys.stderr.buffer.write(bytes([0xB7]))\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "WORKER_PATH", worker)

    with pytest.raises(runner.ScanError) as exc:
        runner.run_worker({}, hard_timeout_s=5)

    assert exc.value.code == "worker_crash"


def test_contained_handler_uses_normcase_for_windows(tmp_path, monkeypatch):
    # Verify the fix for B2: containment check uses os.path.normcase so Windows
    # case-insensitive filesystems are handled without weakening POSIX behaviour.
    import os, http.server
    from a11y_lens.runner import _ContainedHandler
    # Simulate Windows: case-insensitive via lowercasing normcase
    monkeypatch.setattr(os.path, "normcase", lambda s: s.lower())
    monkeypatch.setattr(os.path, "realpath", lambda p: p)  # identity for controlled strings
    sep = os.sep
    # Create handler without init
    h = _ContainedHandler.__new__(_ContainedHandler)
    h.root = f"C:{sep}tmp{sep}SITE"  # base with uppercase
    # Mock super().translate_path to return a path that differs only in case but is inside base
    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, "translate_path", lambda self, path: f"C:{sep}tmp{sep}site{sep}index.html")
    result = h.translate_path("/index.html")
    assert result == f"C:{sep}tmp{sep}site{sep}index.html"  # allowed, not forbidden
    assert "__forbidden__" not in result
    # Outside path should still be blocked even with case-insensitivity
    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, "translate_path", lambda self, path: f"C:{sep}tmp{sep}site_evil{sep}secret.txt")
    result2 = h.translate_path("/evil")
    assert "__forbidden__" in result2
    # Exact base match with different case should be allowed
    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, "translate_path", lambda self, path: f"C:{sep}TMP{sep}SITE")
    h.root = f"C:{sep}tmp{sep}site"  # lower base, upper resolved
    result3 = h.translate_path("/")
    assert "__forbidden__" not in result3


def test_contained_handler_preserves_posix_behavior(tmp_path, monkeypatch):
    # On POSIX normcase is identity; containment should remain strict.
    import os, http.server
    from a11y_lens.runner import _ContainedHandler
    # Ensure normcase is identity (POSIX default)
    monkeypatch.setattr(os.path, "normcase", lambda s: s)
    monkeypatch.setattr(os.path, "realpath", lambda p: p)
    sep = "/"  # use POSIX separator explicitly for this test
    h = _ContainedHandler.__new__(_ContainedHandler)
    h.root = f"{sep}tmp{sep}site"
    # Need to patch the handler logic to use posix sep for this test: we simulate by patching os.sep
    monkeypatch.setattr(os, "sep", sep)
    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, "translate_path", lambda self, path: f"{sep}tmp{sep}site{sep}index.html")
    assert "__forbidden__" not in h.translate_path("/index.html")
    monkeypatch.setattr(http.server.SimpleHTTPRequestHandler, "translate_path", lambda self, path: f"{sep}tmp{sep}Site{sep}index.html")
    # On POSIX, different case is a different directory -> should be blocked (not inside base)
    result = h.translate_path("/index.html")
    assert "__forbidden__" in result
