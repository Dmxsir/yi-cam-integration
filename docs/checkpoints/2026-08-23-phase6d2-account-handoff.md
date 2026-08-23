# Checkpoint — 2026-08-23 — Phase 6D.2 account credential handoff

## Status

- Phase 6D.1 packaging: COMPLETE.
- HA OS bootstrap: COMPLETE.
- **Phase 6D.2: ACTIVE.**

## Goal

Replace manual `yi.env` editing with an authenticated Integration → App API flow.

The App endpoint is:

```text
GET  /api/v1/account
POST /api/v1/account
```

Both routes are protected by the same bearer token that Supervisor discovery gives only to the Home Assistant Integration.

## Security contract

`POST /api/v1/account`:

1. accepts only a bounded `application/json` object;
2. requires explicit YI account/region/country and the already-proven client metadata;
3. validates the account against YI login + device listing before persistence;
4. persists only the input account configuration to the App's `/data/yi.env` path;
5. writes atomically with mode `0600`;
6. updates the running App environment only after successful validation/persistence;
7. triggers normal secret-safe backend discovery;
8. never returns or persists YI `userid`, `token`, `token_secret`, camera password, UID/DID, InitString or license/device-key material.

`GET /api/v1/account` returns only configured state, region, country, file-mode status and `secrets_exposed=false`; it never returns the account or password.

## Implementation

Added:

- `yi_account_credentials.py`
- `tests/test_yi_account_credentials.py`
- `tools/phase3_pppp_probe/run_phase6d_account_handoff_smoke.sh`

Updated:

- `yi_addon_service.py`

The App startup JSON also now includes secret-safe `account_configured` state.

## Development gate

Run:

```bash
PYTHON=~/Documents/yi-cam-integration/.venv/bin/python \
  bash tools/phase3_pppp_probe/run_phase6d_account_handoff_smoke.sh
```

Required final marker:

```text
PHASE6D_ACCOUNT_HANDOFF_SMOKE=PASS
```

## HA OS gate after development smoke

Rebuild the Local App with the updated bundle, then prove:

1. startup remains healthy with the existing empty account state;
2. unauthenticated `GET/POST /api/v1/account` are rejected;
3. authenticated account status returns `configured=false` before handoff;
4. a controlled credential handoff validates the real YI account and persists mode-0600 state without echoing secrets;
5. backend discovery returns the expected secret-safe camera inventory count;
6. no camera runtime auto-starts just because the account was configured;
7. after App restart, `account_configured=true`, discovery succeeds, and credentials remain secret.

Do not paste the App API token, YI password, YI cloud tokens or raw camera connection material into checkpoints or chat.
