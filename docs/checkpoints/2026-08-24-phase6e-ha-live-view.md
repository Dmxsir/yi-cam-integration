# Checkpoint — 2026-08-24 — Phase 6E Home Assistant live view

## Status

- Phase 6D one-camera HA OS long-run: **PASS** — PTZ ran 60 minutes with `restart_count=0`, no exit code, publisher attached and bytes increasing.
- Two-camera HA OS smoke gate: **PASS** — PTZ + pool remained healthy with `restart_count=0` and no exit codes during the accepted test window.
- Phase 6E Home Assistant camera/live-view entities: **PASS for cameras that provide a working upstream live source**.
- `צד בית` is excluded from the live-view integration gate for now because its live view also fails in the official YI application at the same time; this points to an upstream camera/service condition rather than an HA-only failure.

## Home Assistant entity state before the camera fix

The Integration produced 28 entities total: 7 Online binary sensors, 7 Runtime status sensors, 7 Stream switches and 7 Camera entities.

The first camera-platform deployment left every `camera.*` entity as a restored registry state with `state=unavailable` and `restored=true`, while the underlying App runtimes for PTZ and pool were healthy and continuously publishing.

This separated the failure cleanly:

```text
App/runtime/media publication = healthy
HA camera entity registration = failed
```

The issue was Home Assistant camera base initialization. `YiHomeLiveCamera` uses multiple inheritance through `YiHomeCameraEntity` / `CoordinatorEntity` and `Camera`; the initial implementation initialized only the coordinator side. The camera platform now explicitly initializes both bases.

Relevant commit:

```text
125a1199  Initialize Home Assistant camera runtime explicitly
```

## App-owned live-view architecture

The Home Assistant camera entity does not connect to a YI camera directly and does not store or expose camera credentials.

The flow remains:

```text
YI camera
  -> native PPPP/TNP runtime owned by YI Home App
  -> H.264 + AAC relay
  -> App-owned go2rtc stream
  -> internal RTSP endpoint
  -> Home Assistant camera entity / stream integration
```

The Integration receives only secret-safe runtime/publication state and the App-internal media endpoint metadata already derived from immutable stable identity.

Implemented pieces:

```text
bfd7e0a7  Add camera platform to YI Home integration
fb553480  Expose App-owned RTSP streams as HA cameras
107e923c  Add fresh camera status API client
caad6844  Use fresh App publication state for HA live view
3b65480a  Load Home Assistant stream support for YI cameras
125a1199  Initialize Home Assistant camera runtime explicitly
```

## Result

After the camera initialization fix, every tested camera that is online and able to provide live video upstream renders a live feed through its Home Assistant `camera.*` entity.

PTZ and pool are confirmed working through Home Assistant while their App runtime diagnostics remain healthy.

`צד בית` does not currently render, but the same camera also fails to load in the official YI application. It should therefore not be treated as evidence of a YI Home Integration regression unless the official application starts streaming it while Home Assistant still cannot.

## Branding note

YI branding assets were corrected to Home Assistant-friendly square dimensions:

```text
App icon:         yi_home/icon.png
Integration icon: custom_components/yi_home/brand/icon.png
```

Home Assistant may reuse an integration brand icon when rendering devices belonging to that integration; the camera `DeviceInfo` does not explicitly assign the YI icon per camera.

## Next gate

Phase 6E can move past basic live view. Next work should focus on product polish and failure behavior rather than another media architecture change:

1. Camera/entity availability semantics when a camera is offline, stopped, starting, or publishing without ready media.
2. Clean translations and user-facing entity/device labels.
3. Diagnostics and reauthentication UX while preserving the secret-redaction contract.
4. Dynamic camera additions/removals where practical.
5. Final secret-redaction tests.
6. Repeat multi-camera soak and Frigate interoperability as regression gates before release.

## Security

No YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString, raw per-camera connection material, process command line or PID is exposed by the Home Assistant camera entity.
