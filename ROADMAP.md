# YI Home Integration Roadmap

The target product architecture is documented in [`docs/product-architecture.md`](docs/product-architecture.md).
The detailed implementation sequence and exit gates are documented in [`docs/development-plan.md`](docs/development-plan.md).

## Product target

- **YI Home Add-on = engine/runtime**
- **YI Home Custom Integration = Home Assistant UI/devices/entities**
- **Frigate = optional media consumer**
- No Android phone, ADB, SD-card hack, manual model whitelist, or per-camera YAML in the final user experience.

## Completed research/proof phases

### Phase 1–2 — Cloud/APK/TNP research — COMPLETE

- APK-derived YI cloud authentication understood.
- Device inventory and TNP connection material retrieval established.
- Official-client/oracle behavior used to validate protocol details.

### Phase 3 — Native Linux PPPP/TNP media — COMPLETE

- Phone-free Linux PPPP connection proven.
- Native TNP authentication proven.
- H264 1920x1080 video extraction proven.
- Native AAC-LC 16 kHz mono extraction proven.
- MPEG-TS / RTSP publication through go2rtc proven.

### Phase 4 — Frigate interoperability — COMPLETE

- Native YI RTSP consumed by Frigate.
- Detection and recording path proven.
- Audio path identified and validated.

### Phase 5 — Multiple cameras and recovery — COMPLETE

- Two simultaneous native PPPP/TNP sessions proven (`warehouse` + `pool`).
- Per-camera session isolation proven.
- Media-stall watchdog implemented.
- Fault injection with frozen pool QEMU proved automatic recovery without restarting go2rtc or the warehouse camera.

## Phase 6 — Add-on backend foundation — ACTIVE

### Phase 6A — Generic account discovery core — COMPLETE

Goal: remove Phase 3 single-camera assumptions and build the future Add-on Camera Manager.

Live account proof (2026-08-23):

- 7/7 cameras discovered automatically.
- 7/7 reported TNP (`p2p_type=2`).
- 7/7 camera credentials decrypted successfully.
- 7/7 `/v4/tnp/device_info` requests succeeded.
- 7/7 cameras reported `tnp_material_ready=true` and `probe_candidate=true`.
- Raw cloud models observed: `89`, `83`, `40`, `89`, `5`, `51`, `83`.
- Production streams were not modified by discovery.

Exit criteria: PASS.

### Phase 6B — Generic camera runtime and capability probe — COMPLETE

Completed implementation:

- `yi_camera_runtime.py` — reusable Add-on backend/runtime material provider.
- `yi_native_av_relay_stable.py` — stable-id development adapter around the proven native relay.
- `yi_capability_cache.py` — atomic persistent secret-safe per-camera capability cache.
- Generic runtime prefers a previously proven cached profile when available.

Live evidence:

- PTZ raw model `40` passed PPPP/TNP and H264 1920x1080 + AAC 16 kHz mono through the generic stable-id path.
- Pool raw model `83` passed production cutover through the same generic stable-id path.
- Live PTZ probe wrote and read back a successful capability record.

Exit criteria: PASS.

### Phase 6C — Add-on service/API — ACTIVE

Goal: turn the reusable backend into the long-running engine that will be packaged as the Home Assistant Add-on.

#### Phase 6C.1 — Backend state + HTTP API — COMPLETE

Implemented and proven:

- `yi_addon_backend.py` state core.
- `yi_addon_service.py` versioned HTTP API.
- `/health`, `/cameras`, per-camera status and `/discover`.
- Loopback default, bearer token requirement for non-loopback binding.
- Secret-field scan passed.
- Graceful shutdown passed.
- `PHASE6C_API_SMOKE=PASS`.

#### Phase 6C.2 — Per-camera runtime lifecycle manager — COMPLETE

Implemented:

- One independent supervised runtime per `stable_id`.
- Start/stop/restart selected camera only.
- Automatic recreation after supervisor exit/stall with bounded backoff.
- Structured states: `stopped`, `starting`, `running`, `restarting`, `stopping`, `error`.
- Global backend shutdown stops managed runtimes and descendants.

Live PTZ lifecycle proof (2026-08-23):

- Runtime started through HTTP and reached `running`.
- Native media readers/mux startup was observed.
- Manual restart replaced lifecycle PID `7373` with PID `7422`.
- Stop removed the stable relay cleanly.
- Service shutdown left no runtime descendants.
- `PHASE6C_LIFECYCLE_SMOKE=PASS`.

Exit criteria: PASS.

#### Phase 6C.3 — Runtime control API — COMPLETE

Implemented:

- `POST /api/v1/cameras/{stable_id}/start`
- `POST /api/v1/cameras/{stable_id}/stop`
- `POST /api/v1/cameras/{stable_id}/restart`
- Idempotent lifecycle behavior and structured runtime state.
- Per-camera backend operation locks serialize concurrent control/reprobe operations for the same camera.
- Different camera controllers remain independent.

HTTP-only start/status/restart/stop exit gate passed as part of `PHASE6C_LIFECYCLE_SMOKE=PASS`.

Exit criteria: PASS.

#### Phase 6C.4 — Live reprobe + cache refresh — ACTIVE

Current implementation:

- `yi_capability_probe_runtime.py` — reusable bounded live reprobe core.
- `POST /api/v1/cameras/{stable_id}/reprobe` now performs a real live probe.
- A running camera is isolated before reprobe and restored afterward.
- Capability cache is updated only after observed H264 + AAC success.
- Failed probes do not overwrite an existing proven cache record.
- Reprobe responses expose only secret-safe capability/runtime state.
- `tools/phase3_pppp_probe/run_phase6c_reprobe_smoke.sh` validates the full HTTP reprobe flow using an isolated temporary cache.

Exit gate pending live proof:

- HTTP reprobe refreshes capability `observed_at`/source for PTZ.
- PTZ resumes `running` with a new runtime PID after the probe.

#### Phase 6C.5 — Add-on-owned RTSP publication — PLANNED

- Remove dependency on hand-maintained development go2rtc entries.
- Stable media endpoint derived from immutable `stable_id`.
- Add-on/service owns publisher configuration and restart behavior.
- Two concurrent Add-on-managed RTSP streams must survive isolated camera recovery.

#### Phase 6C.6 — Persistence/startup policy — PLANNED

- Persist non-secret runtime state/cache under Add-on `/data`.
- Restore intended camera runtime state after backend restart.
- Safe boot behavior during temporary YI cloud outage.

Phase 6C closes only after 6C.1–6C.6 pass.

### Phase 6D — Home Assistant Add-on packaging — PLANNED

Goal: move the engine/runtime from development infrastructure into HA OS/Supervisor.

Planned stages:

- 6D.1 container/native runtime packaging.
- 6D.2 Add-on options, credential handling and persistent `/data`.
- 6D.3 API/RTSP networking and health checks.
- 6D.4 architecture support/validation.

Exit gate:

- Fresh HA OS Add-on install discovers the account, exposes at least two camera streams, and survives Add-on restart without terminal configuration.

### Phase 6E — Home Assistant Custom Integration — PLANNED

Goal: expose the Add-on cleanly inside Home Assistant.

Planned stages:

- 6E.1 Config Flow and Add-on/API validation.
- 6E.2 Device Registry entries based on `stable_id`.
- 6E.3 camera/status/control entities.
- 6E.4 secret-safe diagnostics.

Exit gate:

- Add Integration → YI Home automatically creates devices/entities and live camera view without YAML.

### Phase 6F — Zero-manual-config onboarding — PLANNED

Target user experience:

```text
Install Add-on
 -> Add YI Home Integration
 -> enter account details / region
 -> Found N cameras
 -> Finish
```

No UID/DID/model/RTSP/YAML required from the user.

Exit gate: a fresh setup can be completed from the Home Assistant UI without terminal access.

### Phase 6G — Frigate integration/export — PLANNED

- Stable Add-on-owned RTSP endpoints.
- Documentation/config helper from safe camera metadata.
- Frigate remains optional and separate from core Home Assistant camera support.

Exit gate: Frigate can consume the Add-on stream without any change to YI runtime code.

## Later work

- Real timestamp/timebase cleanup for native media.
- Additional TNP profiles and model coverage.
- Camera controls/PTZ where supported.
- Motion/event integration without requiring continuous cloud polling.
- Performance work to reduce or eliminate QEMU where feasible.
- Packaging/release automation and HACS/Add-on repository distribution.

## Non-goals for the final product

The following are development/proof mechanisms, not the intended final UX:

- Running production relays manually on a laptop.
- Editing go2rtc or Frigate YAML per YI camera.
- Selecting cameras by display name.
- Maintaining a hardcoded list of supported raw model numbers.
- Requiring an Android phone, ADB, or YI Hack SD card.
