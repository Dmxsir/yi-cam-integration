# YI Home Integration Roadmap

The target product architecture is documented in [`docs/product-architecture.md`](docs/product-architecture.md).
The detailed implementation sequence and exit gates are documented in [`docs/development-plan.md`](docs/development-plan.md).
Home Assistant App packaging requirements are documented in [`docs/home-assistant-app-requirements.md`](docs/home-assistant-app-requirements.md).

## Product target

- **YI Home App/Add-on = engine/runtime**
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

- 7/7 cameras discovered automatically.
- Stable secret-safe camera IDs established.
- No model whitelist is required for runtime selection.
- TNP readiness and credential decryption checks are reusable backend functionality.

Exit criteria: PASS.

### Phase 6B — Generic camera runtime and capability probe — COMPLETE

- Generic runtime resolves cameras by `stable_id`.
- PTZ raw model `40` and pool raw model `83` proved the generic TNP-v2 media profile.
- Persistent secret-safe capability cache implemented and live write/read proven.

Exit criteria: PASS.

### Phase 6C — Add-on service/API — ACTIVE

Goal: turn the reusable backend into the long-running engine that will be packaged as the Home Assistant App/Add-on.

#### Phase 6C.1 — Backend state + HTTP API — COMPLETE

- Secret-safe versioned API implemented.
- Discovery, inventory, status and health endpoints proven.
- Graceful HTTP shutdown and secret-field scan passed.
- `PHASE6C_API_SMOKE=PASS`.

#### Phase 6C.2 — Per-camera runtime lifecycle manager — COMPLETE

- One independent supervised runtime per `stable_id`.
- Start/stop/restart selected camera only.
- Automatic recreation after supervisor exit/stall with bounded backoff.
- Global shutdown removes managed runtime descendants.
- `PHASE6C_LIFECYCLE_SMOKE=PASS`.

#### Phase 6C.3 — Runtime control API — COMPLETE

- `POST /api/v1/cameras/{stable_id}/start`
- `POST /api/v1/cameras/{stable_id}/stop`
- `POST /api/v1/cameras/{stable_id}/restart`
- Per-camera operation serialization prevents conflicting control operations.

Exit criteria: PASS.

#### Phase 6C.4 — Live reprobe + cache refresh — COMPLETE

Implemented:

- `POST /api/v1/cameras/{stable_id}/reprobe` performs a real bounded live capability proof.
- Reprobe uses the same continuous MPEG-TS stdout path as the production runtime.
- Running camera is isolated before reprobe and restored afterward.
- Capability cache is updated atomically only after observed H264 + AAC success.
- Failed probes do not overwrite previous proven capability data.
- Probe process groups are bounded and cleaned on timeout/Add-on shutdown.
- Reprobe diagnostics remain secret-safe.

Live PTZ proof (2026-08-23):

- Initial runtime reached native media.
- HTTP reprobe returned success on the first attempt.
- Capability cache source updated to `addon_api_reprobe`.
- Observed media remained H264 1920x1080 + AAC 16 kHz mono.
- Independent isolated-cache readback passed.
- Runtime resumed with a new lifecycle PID and reached native media again.
- Stop, service shutdown and probe descendant cleanup all passed.
- `PHASE6C_REPROBE_SMOKE=PASS`.

Exit criteria: PASS.

#### Phase 6C.5 — Add-on-owned RTSP publication — ACTIVE

Design locked:

- Add-on service owns one shared managed go2rtc publisher process.
- go2rtc is a media publisher only; it does **not** own PPPP/TNP runtime lifecycle.
- Add-on generates go2rtc configuration automatically from discovered `stable_id` values.
- Each camera gets an empty go2rtc destination stream derived only from immutable `stable_id`.
- Lifecycle-managed MPEG-TS is pushed into go2rtc using its incoming MPEG-TS HTTP endpoint.
- Friendly camera names are metadata only and never form part of stable RTSP URLs.

Target endpoint:

```text
rtsp://<addon-host>:8554/yi_<stable-id-prefix>
```

Implementation/exit gate:

- Shared publisher starts/stops with the backend.
- API exposes per-camera secret-safe RTSP metadata.
- Start/stop/restart of one camera attaches/detaches only that camera's incoming MPEG-TS producer.
- Two Add-on-managed RTSP streams validate H264 + AAC concurrently.
- Force-stalling one camera recovers only that camera while go2rtc and the other stream remain alive.

#### Phase 6C.6 — Persistence/startup policy — PLANNED

- Persist non-secret runtime preferences and capability cache under Add-on `/data`.
- Restore intended camera runtime state after backend restart.
- Safe boot behavior during temporary YI cloud outage.

Phase 6C closes only after 6C.1–6C.6 pass.

### Phase 6D — Home Assistant App/Add-on packaging — PLANNED

Current packaging direction is based on the 2026 Home Assistant App specification:

- `repository.yaml` + App folder with `config.yaml`, explicit Docker `FROM`, AppArmor and docs.
- Initial architecture target: `amd64`; advertise `aarch64` only after runtime proof.
- Persistent state under `/data`.
- No host network, full access, Docker API or Home Assistant config-directory mapping.
- Internal backend API authenticated with an App-generated random token delivered to the Integration through Supervisor discovery.
- RTSP may be exposed separately for optional external Frigate consumers.

Exit gate:

- Fresh HA OS App install discovers the account, exposes at least two streams, and survives App restart without terminal configuration.

### Phase 6E — Home Assistant Custom Integration — PLANNED

- Config Flow uses Supervisor/App discovery (`async_step_hassio`).
- One Device Registry entry per camera based on immutable `stable_id`.
- Camera/status/control entities and secret-safe diagnostics.

Exit gate:

- Add Integration → YI Home automatically creates devices/entities and live camera view without YAML.

### Phase 6F — Zero-manual-config onboarding — PLANNED

Target flow:

```text
Install YI Home App
 -> Add YI Home Integration
 -> enter YI account details / region
 -> Found N cameras
 -> Finish
```

No UID/DID/model/RTSP/YAML required from the user.

### Phase 6G — Frigate integration/export — PLANNED

- Stable App-owned RTSP endpoints.
- Frigate remains optional and separate from core Home Assistant camera support.

## Later work

- Real timestamp/timebase cleanup for native media.
- Additional TNP profiles and model coverage.
- Camera controls/PTZ where supported.
- Motion/event integration.
- Performance work to reduce or eliminate QEMU where feasible.
- Packaging/release automation and HACS/App repository distribution.

## Non-goals for the final product

- Running production relays manually on a laptop.
- Editing go2rtc or Frigate YAML per YI camera.
- Selecting cameras by display name.
- Maintaining a hardcoded supported-model list.
- Requiring Android/ADB or YI Hack SD cards.
