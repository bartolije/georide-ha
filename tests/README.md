# Tests

## Two test environments

This repo runs its tests in two complementary venvs because Home Assistant
needs Python 3.12+ but the live GeoRide API tests pair best with the
lighter Python 3.9 venv (HA's bundled aiodns/aiohttp pair fights raw
client tests).

### Lightweight venv (Python 3.9, no Home Assistant)

For the pure helpers / stats / live API tests:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest -m "not live"      # unit only
.venv/bin/pytest -m live -s         # live, prints discovered schemas
```

### HA venv (Python 3.12 via `uv`, full Home Assistant)

For the config-flow tests with `pytest-homeassistant-custom-component`:

```bash
# install uv (one-time, no sudo)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# install Python 3.12 standalone
uv python install 3.12

# create the HA venv
uv venv --python 3.12 .venv-ha
uv pip install --python .venv-ha/bin/python pytest-homeassistant-custom-component

.venv-ha/bin/python -m pytest          # full suite
```

The conftest auto-detects which environment is active: it installs the
import shim when Home Assistant is missing, and skips live tests when HA
is present.

## Live tests (hits the real GeoRide API)

Live tests log in to your real GeoRide account and read your trackers and
recent trips. They are skipped unless credentials are available.

Two ways to provide credentials:

### 1. Environment variables

```bash
export GEORIDE_EMAIL='you@example.com'
export GEORIDE_PASSWORD='your-password'
pytest -m live
```

### 2. Local secrets file (gitignored)

```bash
cp tests/secrets.example.env tests/secrets.local.env
# edit tests/secrets.local.env with your real credentials
pytest -m live
```

`tests/secrets.local.env` is matched by `.gitignore` and must never be
committed. Verify with: `git check-ignore -v tests/secrets.local.env`.

## Running everything

```bash
pytest                # unit + live (if creds present)
pytest -s -m live     # live only, with stdout (useful to see discovered payloads)
```
