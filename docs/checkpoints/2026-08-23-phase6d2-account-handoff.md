# Checkpoint — 2026-08-23 — Phase 6D.2 account credential handoff

## Status

- Phase 6D.1 packaging: COMPLETE.
- HA OS bootstrap: COMPLETE.
- **Phase 6D.2: ACTIVE.**
- Phase 6D.2 development/unit/API packaging gate: **PASS**.
- Next live gate: rebuild the HA OS Local App, then perform authenticated account handoff against the real YI account.

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

## Development gate — PASS

Live development smoke returned:

```text
OK
account_handoff_unit_tests=PASS
account_handoff_authenticated_api=PASS
account_handoff_secret_persistence=PASS
app_context=/home/asaf/Documents/yi-cam-integration-phase3/yi_home
runtime_source=/home/asaf/Documents/yi-cam-integration-phase3/.analysis/phase3/bionic-root
python_source_count=38
runtime_manifest=/home/asaf/Documents/yi-cam-integration-phase3/yi_home/rootfs/opt/yi-home/runtime-manifest.json
secret_files_copied=false
PHASE6D_APP_CONTEXT_PREPARE=PASS
account_handoff_app_packaging=PASS
account_handoff_build_context_secret_scan=PASS
production_modified=false
PHASE6D_ACCOUNT_HANDOFF_SMOKE=PASS
```

This proves the authenticated API contract, validation/persistence boundary, secret-safe responses, App build-context inclusion, and clean packaging before touching the real HA OS account state.

## HA OS live gate

Rebuild the Local App with the updated bundle, then prove:

1. startup remains healthy with the existing empty account state;
2. unauthenticated `GET/POST /api/v1/account` are rejected;
3. authenticated account status returns `configured=false` before handoff;
4. a controlled credential handoff validates the real YI account and persists mode-0600 state without echoing secrets;
5. backend discovery returns the expected secret-safe camera inventory count;
6. no camera runtime auto-starts just because the account was configured;
7. after App restart, `account_configured=true`, discovery succeeds, and credentials remain secret.

The HA internal app hostname for a locally installed app is derived from `{REPO}_{SLUG}` with underscores replaced by hyphens for DNS; for this App the expected internal hostname is `local-yi-home`. This will be verified from the SSH App before using it for the live API call.

Do not paste the App API token, YI password, YI cloud tokens or raw camera connection material into checkpoints or chat.
