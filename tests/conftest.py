"""Test harness: loads the plugin directory as a package and provides a real-browser fixture."""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NAME = "a11y_lens"
if NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(NAME, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = mod
    spec.loader.exec_module(mod)

from a11y_lens import service, store as st  # noqa: E402


def _browser_settings() -> "service.Settings":
    exe = os.environ.get("A11Y_LENS_TEST_BROWSER", "")
    args = os.environ.get("A11Y_LENS_TEST_BROWSER_ARGS", "").split()
    return service.Settings(browser_executable=exe, chromium_args=args)


@pytest.fixture(scope="session")
def browser_ok() -> bool:
    """True if a real browser can scan; browser tests skip (loudly) otherwise."""
    s = _browser_settings()
    from a11y_lens import runner
    try:
        ex = runner.execute_scan(str(ROOT / "demo" / "fixed-reference" / "index.html"), allowed_origins=[], timeout_s=40,
                                 browser_executable=s.browser_executable or None, chromium_args=s.chromium_args)
        return ex["worker"]["status"] == "complete"
    except Exception:
        return False


@pytest.fixture()
def settings(browser_ok):
    if not browser_ok:
        pytest.skip("no usable Chromium (run `hermes a11y install` or set A11Y_LENS_TEST_BROWSER)")
    return _browser_settings()


@pytest.fixture()
def store(tmp_path):
    return st.Store.open_default(tmp_path / "data")


@pytest.fixture()
def demo(tmp_path):
    """Writable copies of the demo sites."""
    broken = tmp_path / "broken"; shutil.copytree(ROOT / "demo" / "broken-site", broken)
    fixed = tmp_path / "fixed"; shutil.copytree(ROOT / "demo" / "fixed-reference", fixed)
    return broken, fixed
