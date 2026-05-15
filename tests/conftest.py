"""Pytest fixtures + conditional import shim.

The integration imports from `homeassistant.*` at package load time. When
Home Assistant is installed in the active venv (e.g. via
`pytest-homeassistant-custom-component` on Python 3.12+), tests load the
real integration directly. When HA is not available (e.g. the lightweight
Python 3.9 venv used for live API tests), this conftest installs a minimal
shim so the API client and `const.py` can still be loaded for testing the
network layer in isolation.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# 1. Detect whether Home Assistant is installed in this venv
# ---------------------------------------------------------------------------
try:
    import homeassistant  # noqa: F401

    _HA_NATIVE = True
except ImportError:
    _HA_NATIVE = False

# ---------------------------------------------------------------------------
# 2. Without HA, install a minimal shim so `from georide.api import X` works
# ---------------------------------------------------------------------------
if not _HA_NATIVE:
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = types.ModuleType("homeassistant")

    if "homeassistant.const" not in sys.modules:
        _ha_const = types.ModuleType("homeassistant.const")

        class _Platform:
            BINARY_SENSOR = "binary_sensor"
            DEVICE_TRACKER = "device_tracker"
            LOCK = "lock"
            SENSOR = "sensor"
            SIREN = "siren"
            SWITCH = "switch"

        _ha_const.Platform = _Platform
        sys.modules["homeassistant.const"] = _ha_const

    _GR_DIR = Path(__file__).parent.parent / "custom_components" / "georide"
    _pkg = types.ModuleType("georide")
    _pkg.__path__ = [str(_GR_DIR)]
    sys.modules["georide"] = _pkg

    def _load(submod: str) -> types.ModuleType:
        name = f"georide.{submod}"
        spec = importlib.util.spec_from_file_location(name, _GR_DIR / f"{submod}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        setattr(_pkg, submod, module)
        return module

    _load("const")
    _load("api")

# When HA is native, the path is set by pyproject's `pythonpath` and
# `from georide.api import X` works through the normal import system.
from georide.api import GeoRideApiClient  # noqa: E402

# ---------------------------------------------------------------------------
# 3. Credentials loader (for live tests)
# ---------------------------------------------------------------------------
_SECRETS_FILE = Path(__file__).parent / "secrets.local.env"


def _load_secrets_file_into_env() -> None:
    if not _SECRETS_FILE.exists():
        return
    for raw in _SECRETS_FILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_secrets_file_into_env()


# ---------------------------------------------------------------------------
# 4. Fixtures for live API tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def georide_credentials() -> tuple[str, str]:
    email = os.environ.get("GEORIDE_EMAIL")
    password = os.environ.get("GEORIDE_PASSWORD")
    if not email or not password:
        pytest.skip(
            "GEORIDE_EMAIL / GEORIDE_PASSWORD not set "
            "(env vars or tests/secrets.local.env)"
        )
    return email, password


@pytest_asyncio.fixture
async def aiohttp_session():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest_asyncio.fixture
async def authed_client(aiohttp_session, georide_credentials):
    email, password = georide_credentials
    client = GeoRideApiClient(aiohttp_session)
    await client.login(email, password)
    return client


# ---------------------------------------------------------------------------
# 5. HA-only fixtures — auto-enable the pytest-homeassistant-custom-component
#    plugin when running on a venv that has it installed
# ---------------------------------------------------------------------------
if _HA_NATIVE:
    pytest_plugins = ("pytest_homeassistant_custom_component",)

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):
        """Required by pytest-homeassistant-custom-component to find our package."""
        yield


# ---------------------------------------------------------------------------
# 6. Cross-venv routing: live tests need raw aiohttp (works in py3.9 .venv).
#    HA's bundled aiodns/aiohttp pair fights live tests in .venv-ha, so we
#    skip live runs there and rely on the lightweight venv for live coverage.
# ---------------------------------------------------------------------------
def pytest_collection_modifyitems(config, items):
    if _HA_NATIVE:
        skip_live = pytest.mark.skip(
            reason="Live tests run in the .venv (py3.9) venv only; "
            "HA's bundled aiohttp/aiodns versions break raw client calls."
        )
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
