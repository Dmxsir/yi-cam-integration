# YI Home Integration Roadmap

The target product architecture is documented in [`docs/product-architecture.md`](docs/product-architecture.md).

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

### Phase 6B — Generic camera runtime and capability probe — ACTIVE

Goal: start a camera from `stable_id`, not camera name/model constants.

Requirements:

- Generic runtime material lookup through Camera Manager.
- Safe profile/capability probing.
- Observed capabilities determine support.
- Cache successful profile/capability results.
- Integrate existing per-camera session supervisor.
- Maintain isolation between camera runtimes.

Implementation direction:

- `yi_camera_runtime.py` — reusable Add-on backend/runtime material provider.
- `yi_native_av_relay_stable.py` — development adapter that feeds a `stable_id` runtime into the already-proven native relay.
- `yi_capability_cache.py` — persistent secret-safe per-camera profile/media capability cache.
- `tools/phase3_pppp_probe/run_phase6b_stable_probe.sh` — compact development probe wrapper; successful H264/AAC observations are recorded in the capability cache.
- `tools/phase3_pppp_probe/run_phase6b_pool_stable_cutover.sh` — safe production proof that replaces only the pool selector with a `stable_id` runtime and rolls back automatically on validation failure.
- The initial safe probe profile reuses the proven TNP-v2 command sequence. Success is determined by observed H264/AAC output, not raw model number.
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
- This proves a known model-83 camera also works through the generic `stable_id` path in the supervised production topology.
- A raw model `89` attempt failed at `PPPP_Connect`; the same camera was also unavailable in the official YI app at the time, so that result is classified as camera/runtime reachability failure rather than profile incompatibility.

Exit criteria status:

- Known model-83 cameras work through the generic path. **PASS: pool model 83.**
- At least one additional raw model is tested without adding a model whitelist. **PASS: PTZ model 40.**
- Capability/profile result caching is implemented. **IMPLEMENTED; live cache write/read proof pending.**

### Phase 6C — Add-on service/API — PLANNED

Goal: turn the backend into a long-running service suitable for a Home Assistant Add-on.

Initial API direction:

- `GET /api/v1/health`
- `GET /api/v1/cameras`
- `GET /api/v1/cameras/{stable_id}`
- `GET /api/v1/cameras/{stable_id}/status`
- `POST /api/v1/discover`
- `POST /api/v1/cameras/{stable_id}/restart`
- `POST /api/v1/cameras/{stable_id}/reprobe`

Requirements:

- Versioned API.
- Secret-safe responses.
- Structured runtime state.
- Per-camera lifecycle management.
- Graceful startup/shutdown.

### Phase 6D — Home Assistant Add-on packaging — PLANNED

Goal: package the engine/runtime for HA OS/Supervisor.

Requirements:

- Add-on Docker image.
- Multi-architecture strategy documented/tested.
- Native runtime dependencies packaged.
- Add-on config/options schema.
- Secure credential handling.
- Internal API and RTSP ports.
- Health checks and persistent state/cache.

### Phase 6E — Home Assistant Custom Integration — PLANNED

Goal: expose the Add-on cleanly inside Home Assistant.

Requirements:

- Config Flow.
- Add-on discovery/connectivity check.
- Device Registry entries based on `stable_id`.
- `camera` entities.
- Online/runtime/connectivity sensors.
- Diagnostic data with secrets removed.
- Restart/reprobe controls where useful.

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

### Phase 6G — Frigate integration/export — PLANNED

- Stable RTSP endpoints from the Add-on.
- Documentation/generation helpers for Frigate.
- Frigate remains optional and separate from core Home Assistant camera support.

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
