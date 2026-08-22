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

### Phase 6A — Generic account discovery core — IN PROGRESS

Goal: remove Phase 3 single-camera assumptions and build the future Add-on Camera Manager.

Requirements:

- Login once per account session.
- Enumerate all cameras automatically.
- Deterministic secret-safe `stable_id` per camera.
- Raw/normalized models retained as metadata only.
- No target camera names or model whitelist.
- Secret-safe TNP material readiness checks.
- Development CLI is only an adapter around reusable backend classes.

Current implementation: `yi_camera_manager.py`.

Exit criteria:

- Full account inventory is discovered without hardcoded camera names.
- Eligible TNP cameras can obtain secret-bearing runtime material by `stable_id`.
- No production stream is modified during discovery.

### Phase 6B — Generic camera runtime and capability probe — NEXT

Goal: start a camera from `stable_id`, not camera name/model constants.

Requirements:

- Generic runtime material lookup through Camera Manager.
- Safe profile/capability probing.
- Observed capabilities determine support.
- Cache successful profile/capability results.
- Integrate existing per-camera session supervisor.
- Maintain isolation between camera runtimes.

Exit criteria:

- Known model-83 cameras work through the generic path.
- At least one additional raw model is tested without adding a model whitelist.

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
