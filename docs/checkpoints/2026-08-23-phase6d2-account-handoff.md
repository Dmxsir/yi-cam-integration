# Checkpoint — 2026-08-23 — Phase 6D.2 account credential handoff

## Status

- Phase 6D.1 packaging: COMPLETE.
- HA OS bootstrap: COMPLETE.
- **Phase 6D.2: ACTIVE.**
- Phase 6D.2 development/unit/API packaging gate: **PASS**.
- HA OS updated App startup/account-security gate: **PASS**.
- Next live gate: authenticated real-account handoff, discovery, then restart persistence.

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
- `tools/phase3_pppp_probe/run_phase6d_haos_account_handoff.sh`

Updated:

- `yi_addon_service.py`

The App startup JSON also includes secret-safe `account_configured` state.

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

## HA OS updated App/security gate — PASS

The rebuilt Local App started with the expected empty-account state:

```text
Backend API token reused; mode=600; value_exposed=false.
{"service":"yi-home-addon","api_version":"v1","bind":"0.0.0.0","port":8099,"authentication":"bearer","runtime_lifecycle_ready":true,"reprobe_ready":true,"media_publisher_enabled":true,"persistence_enabled":true,"managed_runtime_count":0,"account_configured":false,"initial_discovery_ok":false,"discovery_retry_enabled":true,"secrets_exposed":false}
Published YI Home discovery information to Home Assistant.
YI Home backend is ready.
```

The internal Local App hostname resolved as `local-yi-home`. An unauthenticated request to `GET /api/v1/account` returned HTTP `401` with the secret-safe `unauthorized` error and `secrets_exposed=false`.

This proves the live HA OS endpoint is reachable only with the App bearer credential and that configuring the account has not auto-started any camera runtime.

## Live handoff helper

`run_phase6d_haos_account_handoff.sh` performs the temporary live-gate handoff without echoing secrets:

- reads the existing private `.env.local` used for prior live tests;
- sends the JSON body over encrypted SSH stdin rather than command-line arguments;
- obtains YI Home discovery credentials from Supervisor `/discovery` inside Terminal & SSH using `SUPERVISOR_TOKEN`;
- never prints either Supervisor/App bearer token or the YI account password;
- prints only the secret-safe account API status/result.

The first live helper attempt reached the App but got HTTP `401`. The unauthenticated endpoint test had already proven the App API itself was functioning, so this failure was isolated to discovery-token selection rather than YI account authentication. Supervisor discovery can contain multiple records for the same App/service across repeated publication events. The helper was tightened to enumerate all unique `local_yi_home` / `yi_home` discovery token candidates and select only a candidate that authenticates successfully against `GET /api/v1/account`; token values remain hidden. It now emits only candidate count and `authenticated_discovery_token_found=true` before the handoff.

This helper is a development/live-gate tool only. The final product flow remains Home Assistant Integration UI → authenticated App API.

## Remaining HA OS live gate

Prove:

1. authenticated account status is `configured=false` before handoff;
2. real-account handoff validates against YI and persists mode `0600` without echoing secrets;
3. backend discovery returns the expected secret-safe camera inventory count;
4. `managed_runtime_count` remains `0` immediately after account configuration;
5. after App restart, `account_configured=true`, initial discovery succeeds, credentials remain secret, and no unwanted camera runtime is started.

Do not paste the App API token, YI password, YI cloud tokens or raw camera connection material into checkpoints or chat.
