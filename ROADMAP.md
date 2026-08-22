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

Requirements completed:

- Login once per account session.
- Enumerate all cameras automatically.
- Deterministic secret-safe `stable_id` per camera.
- Raw/normalized models retained as metadata only.
- No target camera names or model whitelist.
- Secret-safe TNP material readiness checks.
- Development CLI is only an adapter around reusable backend classes.

Implementation: `yi_camera_manager.py`.

Live account proof (2026-08-23):

- 7/7 cameras discovered automatically.
- 7/7 reported TNP (`p2p_type=2`).
- 7/7 camera credentials decrypted successfully.
- 7/7 `/v4/tnp/device_info` requests succeeded.
- 7/7 cameras reported `tnp_material_ready=true` and `probe_candidate=true`.
- Raw cloud models observed: `89`, `83`, `40`, `89`, `5`, `51`, `83`.
- All currently normalize to `UNKNOWN`; this is accepted because model mapping is metadata, not a support whitelist.
- Production streams were not modified by discovery.

Exit criteria: PASS.

### Phase 6B — Generic camera runtime and capability probe — COMPLETE

Goal: start a camera from `stable_id`, not camera name/model constants, and remember proven behavior rather than treating model numbers as a support whitelist.

Completed implementation:

- `yi_camera_runtime.py` — reusable Add-on backend/runtime material provider.
- `yi_native_av_relay_stable.py` — development adapter that feeds a `stable_id` runtime into the already-proven native relay.
- `yi_capability_cache.py` — atomic persistent secret-safe per-camera profile/media capability cache.
- `tools/phase3_pppp_probe/run_phase6b_stable_probe.sh` — compact development probe wrapper; successful H264/AAC observations are recorded in the capability cache.
- `tools/phase3_pppp_probe/run_phase6b_pool_stable_cutover.sh` — safe production proof that replaces only the pool selector with a `stable_id` runtime and rolls back automatically on validation failure.
- Generic runtime prefers a previously proven cached profile when available; cache failure/corruption falls back safely to a probe candidate rather than blocking camera startup.

Live generic-runtime evidence (2026-08-23):

- `ptz`, raw model `40`, resolved only by `stable_id`.
- PPPP initialized and connected successfully.
- TNP-v2 startup commands `4881 -> 9029 -> 768` were accepted.
- TNP authentication response command `4882` returned auth result `0`.
- Native media readers started successfully.
- Observed media: H264 1920x1080 and AAC-LC 16 kHz mono.
- Relay completed with `PHASE3G_NATIVE_AV=PASS` and `rc=0`.
- This proves the generic runtime path is not restricted to raw model `83`.
- `pool`, raw model `83`, was cut over in production to `stable_id=867ecdee5a3692c669f9` while keeping the existing per-camera supervisor.
- Production validation passed for both `yi_warehouse` and `yi_pool`; the pool process was confirmed to be running through `yi_native_av_relay_stable.py` and the warehouse configuration remained unchanged.
- A raw model `89` attempt failed at `PPPP_Connect`; the same camera was also unavailable in the official YI app at the time, so that result is classified as camera/runtime reachability failure rather than profile incompatibility.
- Live PTZ probe wrote a capability record to the persistent cache and an independent read returned the same successful record.
- Cached PTZ profile: `tnp_v2_resolution_1_h264_aac`, H264 1920x1080, AAC 16000 Hz mono.
- Cache output reported `secrets_exposed=false`.

Exit criteria: PASS.

### Phase 6C — Add-on service/API — ACTIVE

Goal: turn the reusable backend into the long-running engine that will be packaged as the Home Assistant Add-on.

#### Phase 6C.1 — Backend state + HTTP API — COMPLETE

Current implementation:

- `yi_addon_backend.py` — thread-safe secret-safe Add-on state core.
- `yi_addon_service.py` — versioned HTTP service.
- `tools/phase3_pppp_probe/run_phase6c_api_smoke.sh` — live API/discovery/cache/graceful-shutdown validation.

Current API surface:

- `GET /api/v1/health`
- `GET /api/v1/cameras`
- `GET /api/v1/cameras/{stable_id}`
- `GET /api/v1/cameras/{stable_id}/status`
- `POST /api/v1/discover`
- `POST /api/v1/cameras/{stable_id}/restart`
- `POST /api/v1/cameras/{stable_id}/reprobe`

Security/runtime rules already implemented:

- Loopback-only binding by default.
- Non-loopback binding requires `YI_ADDON_API_TOKEN` bearer authentication.
- Secret-bearing connection material is never retained in the API backend snapshot.
- Capability cache data is exposed only in its secret-safe form.
- Temporary cloud discovery failure does not kill the service; `/health` remains available and discovery can be retried.
- SIGINT/SIGTERM trigger graceful HTTP shutdown.

Live API smoke proof (2026-08-23):

- Backend and HTTP service compiled successfully.
- Service started on `127.0.0.1:18099`.
- `GET /api/v1/health` returned successfully.
- API returned all 7 discovered cameras.
- One proven cached capability was visible through the API.
- `POST /api/v1/discover` refreshed the account inventory successfully.
- Recursive secret-field scan of API payloads passed.
- SIGTERM graceful shutdown passed.
- Smoke test completed with `PHASE6C_API_SMOKE=PASS`.

Exit criteria: PASS.

#### Phase 6C.2 — Per-camera runtime lifecycle manager — ACTIVE

Next implementation target:

- Backend owns one independent supervised runtime per `stable_id`.
- Start/stop/restart selected camera without affecting others.
- Lifecycle manager recreates a camera runtime after supervisor stall exit.
- Structured states: `stopped`, `starting`, `running`, `restarting`, `stopping`, `error`.
- Global backend shutdown leaves no relay/QEMU/FFmpeg descendants.

#### Phase 6C.3 — Runtime control API — PLANNED

Add/wire:

- `POST /api/v1/cameras/{stable_id}/start`
- `POST /api/v1/cameras/{stable_id}/stop`
- `POST /api/v1/cameras/{stable_id}/restart`

Exit gate: start/status/restart/stop proven through HTTP only.

#### Phase 6C.4 — Live reprobe + cache refresh — PLANNED

- Wire `POST /api/v1/cameras/{stable_id}/reprobe` to a bounded live media probe.
- Update capability cache only after observed H264/AAC success.
- Preserve prior proven record on probe failure.
- Resume previous runtime state when appropriate.

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
