"""Pytest fixtures + import shim.

The `custom_components/georide` package imports from `homeassistant.*` at
module load time. We don't want to install Home Assistant just to test a
pure-aiohttp REST client, so this conftest:

  1. Stubs the few `homeassistant.*` symbols the integration's `const.py`
     transitively needs.
  2. Loads `const.py` and `api.py` directly via `importlib`, bypassing the
     package `__init__.py` (which has heavier HA imports we don't need here).
  3. Registers them in `sys.modules` under the `georide.*` namespace so test
     files can write `from georide.api import GeoRideApiClient` naturally.

If/when proper Home Assistant test infrastructure is added
(pytest-homeassistant-custom-component on a Python >= 3.12 venv), this shim
can be deleted.
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
# 1. Stub homeassistant.const for const.py
# ---------------------------------------------------------------------------
if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")

if "homeassistant.const" not in sys.modules:
    _ha_const = types.ModuleType("homeassistant.const")

    class _Platform:  # only the names const.py / __init__.py reference
        BINARY_SENSOR = "binary_sensor"
        DEVICE_TRACKER = "device_tracker"
        LOCK = "lock"
        SENSOR = "sensor"
        SIREN = "siren"

    _ha_const.Platform = _Platform
    sys.modules["homeassistant.const"] = _ha_const

# ---------------------------------------------------------------------------
# 2. Load api.py + const.py via importlib, register under georide.*
# ---------------------------------------------------------------------------
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

# Late import: now resolves to the importlib-loaded module above.
from georide.api import GeoRideApiClient  # noqa: E402

# ---------------------------------------------------------------------------
# 3. Credentials loader
# ---------------------------------------------------------------------------
_SECRETS_FILE = Path(__file__).parent / "secrets.local.env"


def _load_secrets_file_into_env() -> None:
    """Copy KEY=VALUE lines from secrets.local.env into os.environ (missing-only)."""
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
# 4. Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def georide_credentials() -> tuple[str, str]:
    """Return (email, password) or skip if missing."""
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
