# Checkpoint — 2026-08-24 — Phase 6E dynamic camera inventory

## Status

Implementation is complete and awaiting HA OS validation.

The YI Home Integration now supports periodic account-inventory refresh, camera rename reconciliation and dynamic entity creation for cameras that appear after the Config Entry was created.

## Intended behavior

- YI account inventory is refreshed through the App every 5 minutes.
- Runtime/entity state continues to poll every 30 seconds.
- A cloud inventory refresh failure does not make the existing cached camera inventory unavailable.
- A renamed YI camera keeps the same stable identity, unique IDs and entity IDs.
- Only the integration-provided Home Assistant device name is reconciled to the new YI name.
- A Home Assistant user-defined device name remains untouched.
- A newly discovered camera gets Online, Runtime status, Stream and Camera entities without reloading the integration.
- A camera absent from a later inventory remains registered in Home Assistant but its entities become unavailable because the stable camera record is no longer present. This intentionally avoids automatic entity-registry deletion and preserves automations if the same stable camera returns.

## Identity rule

Camera identity continues to derive from the secret-safe stable ID, not the display name:

```text
YI UID -> SHA-256-derived stable_id -> entity unique IDs / media identity
```

Changing only the YI display name therefore must never change entity identity.

## Relevant commits

```text
3749c38d  Reconcile dynamic YI camera names in Home Assistant
c9c375b7  Add YI online entities dynamically
ed0af5d9  Add YI runtime entities dynamically
4c1a6f92  Add YI stream controls dynamically
08b0e611  Add YI camera entities dynamically
be040bd2  Add App inventory refresh API client
335387d6  Refresh YI account inventory periodically
7ffad21d  Scope YI device reconciliation to its config entry
6aad011a  Use config-scoped YI device name reconciliation
260ff4e8  Allow full YI inventory refresh to complete
```

## Validation gate

1. Deploy only the Custom Integration; the App already exposes the authenticated `/api/v1/discover` endpoint.
2. Confirm all existing entities load normally and the active PTZ camera remains streaming.
3. Rename one camera in the official YI application.
4. Either wait up to five minutes for periodic inventory refresh or reload the YI Home Config Entry to force the first inventory refresh immediately.
5. Confirm the Home Assistant Device display name changes while existing entity IDs remain unchanged.
6. Optional addition test: add a camera to the YI account and confirm its four entities appear without a Home Assistant restart/reload after inventory refresh.

## Security

The integration does not use camera names as identities and does not expose YI UID/DID, camera passwords, YI account credentials, App bearer token, PPPP InitString, license/device keys or raw runtime connection material.
