# Checkpoint — 2026-08-24 — Phase 6E dynamic camera inventory

## Status

Dynamic rename reconciliation: **PASS on HA OS**.

Dynamic new-camera creation: **IMPLEMENTED / NOT YET VALIDATED on HA OS**.

The YI Home Integration now supports periodic account-inventory refresh, camera rename reconciliation and dynamic entity creation for cameras that appear after the Config Entry was created.

## Validated HA OS rename result

The existing PTZ camera was renamed in the official YI application from `ptz` to `PTZ-FRONT` while its stream remained active.

After inventory reconciliation Home Assistant showed the updated integration-provided names while preserving the existing device and entity identities:

```text
Device ID remained: c56c344227c9f89b672aca678a4266d8

binary_sensor.ptz_online   -> friendly name: ptz-front מקוון   -> state: on
camera.ptz_2               -> friendly name: ptz-front         -> state: streaming
sensor.ptz_runtime_status  -> friendly name: ptz-front מצב מנגנון -> state: running
switch.ptz_stream          -> friendly name: ptz-front שידור   -> state: on
```

This proves that a YI display-name change does not recreate the HA camera, does not change its entity IDs and does not interrupt an active stream.

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

## Remaining validation gate

1. Keep the existing validated cameras/runtimes untouched.
2. Add a camera to the YI account, or temporarily remove and re-add a test camera if practical.
3. Do not reload Home Assistant or the YI Home Integration.
4. Wait for the periodic inventory refresh.
5. Confirm the newly discovered camera receives four entities automatically: Online, Runtime status, Stream and Camera.
6. Confirm its stable identity remains independent of the display name.

## Security

The integration does not use camera names as identities and does not expose YI UID/DID, camera passwords, YI account credentials, App bearer token, PPPP InitString, license/device keys or raw runtime connection material.
