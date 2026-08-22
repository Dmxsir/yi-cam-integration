# YI Home Integration – Target Product Architecture

## Decision

The final product is split into two cooperating Home Assistant components:

1. **YI Home Add-on** — the engine/runtime.
2. **YI Home Custom Integration** — the Home Assistant UI/device/entity layer.

The Add-on owns all native and protocol-heavy work. The Integration must never need to understand PPPP/TNP internals, load `libPPPP_API.so`, run QEMU, or manage FFmpeg processes.

This architecture is the target for all work after Phase 5. Laptop scripts remain development/proof tooling only.

## Target topology

```text
YI Cloud / YI Cameras
        |
        | account auth + PPPP/TNP
        v
+-----------------------------------------+
| YI Home Add-on                          |
|                                         |
|  Account Session                        |
|  Camera Manager                         |
|  Auto Discovery                         |
|  Capability / Profile Probe             |
|  Per-camera Runtime Supervisor          |
|  PPPP/TNP Native Runtime                |
|  libPPPP_API.so / QEMU                  |
|  H264 + AAC Relay                       |
|  FFmpeg / go2rtc                        |
|  Local Add-on API                       |
+------------------+----------------------+
                   |
          local API|      RTSP/media
                   |          |
                   v          v
+----------------------+   +----------------+
| HA Custom Integration|   | Frigate        |
|                      |   | optional       |
| Config Flow          |   +----------------+
| Device Registry      |
| Camera entities      |
| Sensors / diagnostics|
| Services / controls  |
+----------------------+
```

## Add-on responsibilities

The Add-on is the **engine** and source of truth for camera runtime state.

It owns:

- YI account authentication.
- `/v4/devices/list` discovery.
- Stable camera identity independent of user-visible camera names.
- Secret storage and secret-bearing TNP connection material.
- PPPP/TNP session creation.
- Automatic capability/profile probing rather than model whitelists.
- Native H264 and audio extraction.
- Per-camera process/session isolation.
- Stall detection and automatic session recreation.
- RTSP/media publication.
- Local versioned API for Home Assistant.
- Secret-safe diagnostics.

The Add-on must tolerate one camera failing without disrupting other cameras.

## Integration responsibilities

The Home Assistant Custom Integration is intentionally lightweight.

It owns:

- Config Flow and onboarding UI.
- Add-on availability/version checks.
- Home Assistant Device Registry entries.
- `camera` entities.
- Connectivity/runtime status sensors.
- Optional diagnostic sensors.
- Services or buttons that call the Add-on API, such as restart/reprobe.
- Translation of Add-on runtime state into Home Assistant state.

It does **not** own native PPPP/TNP transport or media processes.

## User experience target

The user should not need to know a YI raw model number, UID, DID, TNP version, RTSP URL, or edit YAML.

Target setup:

```text
Install YI Home Add-on
        ->
Install / Add YI Home Integration
        ->
Enter YI account credentials / region
        ->
Automatic discovery
        ->
"Found N cameras"
        ->
Devices and camera entities created
```

Frigate support is optional. Frigate consumes media exposed by the Add-on; it is not required for the Home Assistant Integration to work.

## Stable identity

Camera identity must not be based on camera display name.

The Camera Manager generates a deterministic secret-safe `stable_id` from the cloud UID. User renaming a camera must not create a new Home Assistant device.

`stream_id` is an implementation/media identifier and may contain a readable slug, but stable device identity comes from `stable_id`.

## Model handling policy

Raw/normalized YI models are metadata and probing hints, not a hard support whitelist.

Final logic must prefer observed behavior/capabilities:

```text
camera discovered
  -> determine transport
  -> retrieve connection material
  -> try safe known TNP/profile probes
  -> observe video/audio/control responses
  -> cache successful capability profile
```

A camera is only considered unsupported after appropriate protocol/capability probes fail.

## Runtime isolation and self-healing

Each camera has an independent runtime supervisor.

The Phase 5 proof established the required behavior:

```text
PPPP/TNP media stalls
  -> no media progress for configured timeout
  -> terminate the camera relay process group
  -> recreate only that camera session
  -> H264/AAC returns
```

The supervisor must terminate the complete camera process group so QEMU/FFmpeg descendants are not orphaned.

## Add-on API contract direction

The exact API is versioned and will be finalized during Phase 6C. Initial target surface:

```text
GET  /api/v1/health
GET  /api/v1/cameras
GET  /api/v1/cameras/{stable_id}
GET  /api/v1/cameras/{stable_id}/status
POST /api/v1/discover
POST /api/v1/cameras/{stable_id}/restart
POST /api/v1/cameras/{stable_id}/reprobe
```

API responses must never expose cloud UID, DID, InitString, license/device key, camera password, account password, token, or token secret.

## Development rule

From Phase 6 onward, new functionality should be written as reusable Add-on backend/core functionality first. A CLI may exist only as a development/test adapter around the same core.

Production media running on the development laptop is temporary validation infrastructure and must not become the final deployment design.
