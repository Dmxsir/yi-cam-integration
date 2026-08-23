# Checkpoint — 2026-08-23 — Phase 6D.2 account credential handoff

## Status

- Phase 6D.1 packaging: COMPLETE.
- HA OS bootstrap: COMPLETE.
- **Phase 6D.2: ACTIVE.**
- Phase 6D.2 development/unit/API packaging gate: **PASS**.
- HA OS updated App startup/account-security gate: **PASS**.
- Supervisor discovery security boundary: **PROVEN**.
- Minimal Home Assistant custom Integration for Hass.io discovery + account handoff: **IMPLEMENTED, smoke/deploy pending**.
- Next live gate: install the custom Integration in HA Core, complete the YI account form, verify camera discovery, then restart persistence.

## Goal

Replace manual `yi.env` editing with an authenticated Integration → App API flow.

The App endpoint is:

```text
GET  /api/v1/account
POST /api/v1/account
```

Both routes are protected by the App bearer token published through Supervisor discovery to Home Assistant Core.

## Security contract

`POST /api/v1/account` validates the YI account before persistence, writes `/data/yi.env` atomically with mode `0600`, updates the running environment only after successful validation, and never returns or persists YI cloud session tokens or raw camera connection material.

`GET /api/v1/account` returns only configured state, region, country, file-mode status and `secrets_exposed=false`; it never returns the account or password.

The Home Assistant Config Entry stores only App connection metadata (host/port/App bearer token and safe region/country metadata). The YI account and password are not stored in the Config Entry.

## Development gate — PASS

The account handoff development smoke returned:

```text
account_handoff_unit_tests=PASS
account_handoff_authenticated_api=PASS
account_handoff_secret_persistence=PASS
PHASE6D_APP_CONTEXT_PREPARE=PASS
account_handoff_app_packaging=PASS
account_handoff_build_context_secret_scan=PASS
production_modified=false
PHASE6D_ACCOUNT_HANDOFF_SMOKE=PASS
```

## HA OS App/security gate — PASS

The rebuilt Local App started with the expected empty-account state:

```text
Backend API token reused; mode=600; value_exposed=false.
{"service":"yi-home-addon","api_version":"v1","bind":"0.0.0.0","port":8099,"authentication":"bearer","runtime_lifecycle_ready":true,"reprobe_ready":true,"media_publisher_enabled":true,"persistence_enabled":true,"managed_runtime_count":0,"account_configured":false,"initial_discovery_ok":false,"discovery_retry_enabled":true,"secrets_exposed":false}
Published YI Home discovery information to Home Assistant.
YI Home backend is ready.
```

The internal hostname `local-yi-home` resolved correctly. An unauthenticated request to `GET /api/v1/account` returned HTTP `401` with `secrets_exposed=false`.

## Supervisor discovery security boundary — PROVEN

A controlled SSH diagnostic showed:

```text
supervisor_token_present=true
ha_cli=PASS
supervisor_info_http=200
supervisor_discovery_http=401
```

This is expected Home Assistant behavior. Supervisor's discovery list/get handlers are decorated with `require_home_assistant`; an App such as Terminal & SSH may publish discovery but may not read discovery records or credentials belonging to another App. Therefore the temporary SSH helper cannot and must not obtain the YI Home App bearer token from `GET /discovery`.

`tools/phase3_pppp_probe/run_phase6d_haos_account_handoff.sh` is retired and now exits with an explicit explanation rather than attempting to bypass this boundary.

## Home Assistant Integration implementation

Added `custom_components/yi_home/` with:

- `manifest.json` — custom integration metadata and config-flow registration;
- `config_flow.py` — `async_step_hassio(HassioServiceInfo)` consumes YI Home Supervisor discovery;
- `api.py` — bearer-authenticated App API client;
- `__init__.py` — config-entry setup/health validation;
- `const.py` — non-secret connection/client compatibility constants;
- `strings.json` and Hebrew translation.

Flow behavior:

1. Home Assistant Core receives the YI Home discovery message from Supervisor, including the App bearer credential.
2. The Integration validates `/api/v1/health` and `/api/v1/account` using that credential.
3. If the App is not configured, HA displays a password-masked YI account form.
4. The Integration sends the credentials directly to `POST /api/v1/account`.
5. The YI password is not stored in the HA Config Entry.
6. On success, the Config Entry is created from App connection metadata only.

Added `tools/phase3_pppp_probe/run_phase6d_integration_smoke.sh`, which compiles the Integration sources, validates the manifest/Hass.io flow, scans for packaged secret/state material, and creates:

```text
dist/yi_home-integration.tar.gz
```

## Remaining live gate

1. Run the Integration smoke and require `PHASE6D_INTEGRATION_SMOKE=PASS`.
2. Install `custom_components/yi_home` under HA `/config/custom_components` and restart Home Assistant Core.
3. Confirm Supervisor discovery opens the YI Home account flow.
4. Enter the real YI account credentials in the HA UI; do not paste them into logs/chat.
5. Require a successful account handoff with mode `0600`, secret-safe camera inventory, and `managed_runtime_count=0` immediately after configuration.
6. Restart the App and require `account_configured=true`, successful initial discovery, secret safety, and no unwanted camera runtime auto-start.

Do not paste the App API token, YI password, YI cloud tokens or raw camera connection material into checkpoints or chat.
