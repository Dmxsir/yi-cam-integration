# YI Home Integration Roadmap

The target product architecture is documented in [`docs/product-architecture.md`](docs/product-architecture.md).
The detailed implementation sequence and exit gates are documented in [`docs/development-plan.md`](docs/development-plan.md).
Home Assistant App packaging requirements are documented in [`docs/home-assistant-app-requirements.md`](docs/home-assistant-app-requirements.md).

Latest checkpoint: [`docs/checkpoints/2026-08-23-phase6d3-haos-live-stream.md`](docs/checkpoints/2026-08-23-phase6d3-haos-live-stream.md).

## Product target

- **YI Home App/Add-on = engine/runtime**
- **YI Home Custom Integration = Home Assistant UI/devices/entities**
- **Frigate = optional media consumer**
- No Android phone, ADB, SD-card hack, manual model whitelist, UID/DID entry, per-camera YAML or manual RTSP setup in the final user experience.

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

- Two simultaneous native PPPP/TNP sessions proven.
- Per-camera session isolation proven.
- Media-stall watchdog implemented.
- Fault injection proved automatic recovery without restarting go2rtc or the unaffected camera.

## Phase 6 — Product backend + Home Assistant packaging — ACTIVE

### Phase 6A — Generic account discovery core — COMPLETE

- 7/7 cameras discovered automatically.
- Stable secret-safe camera IDs established.
- No model whitelist required for runtime selection.
- TNP readiness and credential decryption checks are reusable backend functionality.

Exit criteria: PASS.

### Phase 6B — Generic camera runtime and capability probe — COMPLETE

- Generic runtime resolves cameras by `stable_id`.
- Cross-model TNP-v2 H264/AAC media profile proven.
- Persistent secret-safe capability cache implemented and live write/read proven.

Exit criteria: PASS.

### Phase 6C — App backend/service — COMPLETE

Completed backend functionality includes:

- versioned secret-safe HTTP API;
- generic account discovery and inventory;
- one independent supervised runtime per `stable_id`;
- start/stop/restart control API;
- bounded reprobe and capability refresh;
- one shared App-managed go2rtc publisher;
- stable per-camera stream identity;
- two-camera concurrent publication and scoped recovery;
- authoritative `PPPP_CheckDevOnline` availability;
- persistent desired-running policy and restart restoration;
- `/data` capability/runtime/publisher state.

Final Phase 6C live gates:

```text
PHASE6C_API_SMOKE=PASS
PHASE6C_LIFECYCLE_SMOKE=PASS
PHASE6C_REPROBE_SMOKE=PASS
PHASE6C_MEDIA_PUBLISHER_SMOKE=PASS
PHASE6C_MEDIA_ISOLATION_SMOKE=PASS
PHASE6C_PERSISTENCE_SMOKE=PASS
```

Exit criteria: PASS. **Phase 6C is complete.**

### Phase 6D — Home Assistant App/Add-on packaging — ACTIVE

#### Phase 6D.1 — App/container scaffold — COMPLETE

Implemented and proven:

- repository-level `repository.yaml` and Local App folder `yi_home/`;
- explicit `ghcr.io/home-assistant/base:3.23` Docker base;
- `amd64` initial target;
- Bionic/native runtime staged without development credentials/state;
- Python/cryptography and QEMU user-mode runtime;
- go2rtc `1.9.14` with pinned SHA-256;
- `/run.sh` with `/data` persistence and mode-0600 internal API token;
- Supervisor `yi_home` discovery;
- protected/AppArmor operation with no host networking, full access or Docker API;
- secret-safe build-context and real Docker-image smoke gates.

HA OS Local App bootstrap is proven at slug `local_yi_home` with source `/addons/yi_home`.

Exit criteria: PASS. **Phase 6D.1 is complete.**

#### Phase 6D.2 — Configuration, storage and secrets — COMPLETE

Implemented and live-proven:

- authenticated `GET/POST /api/v1/account`;
- Integration → App credential handoff;
- account validation before persistence;
- restrictive atomic `/data/yi.env` persistence;
- no YI password in the Home Assistant Config Entry;
- no cloud session token or raw camera connection material in read APIs/diagnostics;
- App-generated backend bearer token persisted mode `0600`;
- restart persistence with `account_configured=true` and successful discovery;
- newly discovered cameras remain stopped unless explicit durable runtime intent exists.

Exit criteria: PASS. **Phase 6D.2 is complete.**

#### Phase 6D.3 — Networking, entities and live HA OS media — ACTIVE

Proven:

- Home Assistant Core reaches the App backend through Supervisor/App discovery;
- one HA Device per discovered camera;
- 7 camera devices registered;
- 3 entities per camera currently registered: Online, Runtime status and Stream control (21 total);
- stream start/stop is controlled through the Integration without per-camera YAML;
- App backend remains internal to the App network;
- optional RTSP exposure remains separate from the Integration control path.

##### FFmpeg regression and packaging fix — COMPLETE

The HA OS live-stream stall was reproduced using the exact App image outside Home Assistant and isolated to Alpine 3.23 FFmpeg 8.0.1.

A/B proof:

```text
Alpine + QEMU 8.2.2 + FFmpeg 8.0.1 = FAIL after roughly 20–30 s
Alpine + QEMU 8.2.2 + FFmpeg 6.0.1-static = PASS for 60 s
```

The complete backend/lifecycle/go2rtc path using the normal App QEMU 10.1.5 plus FFmpeg 6.0.1-static remained stable for 150 seconds with `restart_count=0` and more than 22 MB published. Therefore the QEMU version is not the root cause.

The App now pins FFmpeg/ffprobe `6.0.1-static` with a fixed archive SHA-256 instead of installing Alpine's unpinned `ffmpeg` package. The App-context smoke enforces the pinned runtime.

##### One-camera HA OS live-stream E2E — COMPLETE

After rebuilding and deploying `local_yi_home`, the `ptz` camera remained live with:

```text
desired_running=true
process_alive=true
restart_count=0
last_reason=started
last_exit_code=null
publisher_attached=true
published_bytes=31719424
publisher_error=null
```

Exit criteria for one-camera live media: PASS.

##### Next Phase 6D.3 gate — multi-camera HA OS E2E

1. Keep the proven `ptz` stream running.
2. Enable a second authoritative-online camera, initially `pool`.
3. Require both runtimes to remain stable concurrently for at least 3–5 minutes with no restart/publisher error and monotonically increasing published bytes.
4. Stop/restart one stream and require the other runtime plus shared go2rtc publisher to remain unaffected.
5. Restart the App and require only persisted desired-running + authoritative-online cameras to restore.
6. After the App-native multi-camera gate passes, validate optional Frigate consumption from the stable App-owned RTSP endpoints.

Do not mark Phase 6D complete until the multi-camera HA OS and restart gates pass.

#### Phase 6D.4 — Architecture support — PLANNED

- Initial architecture target remains `amd64` only.
- Advertise `aarch64` only after the full native/QEMU path is independently proven there.

Phase 6D exit gate:

- fresh HA OS App install/start without development-machine files;
- Integration-driven account configuration;
- automatic inventory/device/entity creation;
- at least two simultaneous App-owned live streams;
- persisted desired-running behavior survives App restart;
- no terminal, manual UID/DID/RTSP/YAML or Android dependency in the product flow.

### Phase 6E — Home Assistant Custom Integration — ACTIVE

Foundation already implemented/proven while Phase 6D live packaging work proceeds:

- `async_step_hassio` consumes Supervisor/App discovery;
- backend health/API validation;
- account setup form and authenticated handoff;
- Config Entry created without YI password;
- coordinator-driven camera inventory/status refresh;
- one Device Registry entry per camera using immutable identity;
- Online binary sensor;
- Runtime status sensor with secret-safe lifecycle attributes;
- Stream switch controlling durable App runtime intent;
- 7 devices / 21 entities live-registered in HA OS.

Remaining Integration work:

- camera/live-view entity backed by the App-owned media path;
- polished translations/entity names and user-facing diagnostics;
- dynamic camera additions without manual reload where practical;
- reauthentication/error UX;
- final secret-redaction/diagnostic tests.

Phase 6E exit gate:

- Add YI Home Integration automatically creates camera devices/entities and live view without YAML or protocol internals.

### Phase 6F — Zero-manual-config onboarding — PLANNED

Target flow:

```text
Install YI Home App
 -> Add YI Home Integration
 -> enter YI account details / region
 -> Found N cameras
 -> Finish
```

No UID/DID/model/TNP/RTSP/YAML required from the user.

### Phase 6G — Frigate integration/export — PLANNED

- Stable App-owned RTSP endpoints.
- Frigate remains optional and separate from core Home Assistant camera support.
- Frigate failure must not affect App/Integration lifecycle.

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
