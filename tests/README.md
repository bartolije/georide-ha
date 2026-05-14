# Tests

## Unit tests (no credentials needed)

```bash
pip install -r requirements-test.txt
pytest -m "not live"
```

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
