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
- Fault injection proved automatic recovery without restarting go2rtc or the unaffected camera.

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

- Live bounded reprobe uses the production continuous MPEG-TS path.
- Running camera is isolated and restored around reprobe.
- Capability cache updates atomically only after observed H264 + AAC success.
- Failed probes do not overwrite previous proven capability data.
- Probe descendants are bounded and cleaned on timeout/App shutdown.
- `PHASE6C_REPROBE_SMOKE=PASS`.

#### Phase 6C.5 — Add-on-owned RTSP publication — COMPLETE

Design locked:

- Add-on service owns one shared managed go2rtc publisher process.
- go2rtc publishes media only; PPPP/TNP lifecycle remains owned by the Add-on lifecycle manager.
- go2rtc configuration is generated automatically from immutable `stable_id` values.
- Each camera receives a stable destination stream `yi_<stable-id-prefix>`.
- Lifecycle-managed MPEG-TS is pushed through go2rtc incoming MPEG-TS HTTP ingest.
- Friendly names are metadata only and do not affect media identity.

Target endpoint:

```text
rtsp://<addon-host>:8554/yi_<stable-id-prefix>
```

##### Phase 6C.5A — isolated managed publisher — COMPLETE

Live PTZ proof (2026-08-23):

- Managed go2rtc started with all 7 discovered destination streams.
- Production ports `1984/8554` were untouched.
- MPEG-TS ingest registered a media-ready producer.
- RTSP validated H264 1920x1080 + AAC 16 kHz mono.
- Camera restart changed only the camera runtime PID (`10651` → `10737`).
- Shared go2rtc survived unchanged.
- Producer re-registered media-ready and RTSP recovered.
- Managed publisher cleanup passed.
- `PHASE6C_MEDIA_PUBLISHER_SMOKE=PASS`.

The go2rtc startup probe edge case was fixed by prebuffering the first MPEG-TS chunk before opening incoming HTTP ingest and by distinguishing producer registration from actual detected media readiness.

##### Phase 6C.5B — two-camera + fault isolation — COMPLETE

Live PTZ + pool proof (2026-08-23) on isolated ports `18103/11985/18555`:

- Two different cameras started through backend HTTP concurrently.
- Both publications became registered and media-ready.
- Both RTSP endpoints validated H264 + AAC concurrently.
- Fault injection was scoped to the PTZ relay process group only.
- Pool RTSP remained valid during the PTZ fault.
- PTZ lifecycle PID changed `11272` → `11588` and generation changed `1` → `2`.
- Pool runtime PID/generation remained unchanged.
- Shared go2rtc PID remained unchanged.
- The original faulted runtime descendants were cleaned.
- Both RTSP endpoints validated H264 + AAC again after recovery.
- Dual runtime stop, graceful service shutdown and publisher cleanup passed.
- `PHASE6C_MEDIA_ISOLATION_SMOKE=PASS`.

Exit criteria: PASS. Phase 6C.5 is complete.

#### Phase 6C.6 — Persistence/startup policy — ACTIVE

Policy locked:

- Runtime intent is explicit and durable: `start`/`restart` persist `desired_running=true`; `stop` removes that intent.
- Newly discovered cameras do not auto-start merely because they exist.
- After backend/App restart, only cameras with persisted running intent are restored.
- Temporary reprobe isolation does not alter persisted runtime intent.
- A temporary YI cloud failure at boot does not erase intent or crash the service; initial discovery is retried and pending intent is reconciled after recovery.

Implementation in progress:

- `yi_runtime_policy.py` stores only secret-safe `stable_id` running intent using atomic mode-0600 JSON.
- `yi_persistent_backend.py` adds policy/reconcile behavior without changing the proven media backend.
- `yi_addon_service.py --data-dir <path>` places capability cache, runtime policy, runtime state and managed publisher state under one persistent root; the future App will use `/data`.
- Health exposes secret-safe persistence/reconcile diagnostics.
- Deterministic tests cover policy round-trip, permissions, pending unavailable cameras and cloud-discovery failure preserving pending intent.
- `run_phase6c_persistence_smoke.sh` validates live persistence across three backend launches on isolated ports.

Exit gate:

- Two running camera intents survive backend restart and both streams return automatically.
- Capability cache lives under the persistent data root.
- Explicitly stopping one camera persists; a later restart restores only the still-enabled camera.
- Runtime policy/capability files are secret-safe and mode 0600.
- Cloud-discovery failure keeps desired state pending for retry.
- Service/publisher/runtime cleanup remains correct.

Phase 6C closes only after 6C.6 passes.

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
