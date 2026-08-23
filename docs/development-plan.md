# YI Home Integration – Development Plan

This document expands the high-level roadmap into the implementation order and exit gates for the remaining product work.

The target architecture remains fixed:

- **YI Home App/Add-on = engine/runtime**
- **YI Home Custom Integration = Home Assistant UI/device/entity layer**
- **Frigate = optional media consumer**

Development laptop services and hand-edited go2rtc configuration are validation infrastructure only; they are not the final deployment design.

See also [`home-assistant-app-requirements.md`](home-assistant-app-requirements.md) for the current Home Assistant 2026 App packaging/security/discovery requirements.

## Current position

Completed:

- Phase 1–2: cloud/APK/TNP research.
- Phase 3: phone-free native PPPP/TNP H264 + AAC media.
- Phase 4: Frigate interoperability.
- Phase 5: multi-camera operation and self-healing supervisor.
- Phase 6A: generic account discovery by secret-safe `stable_id`.
- Phase 6B: generic runtime path, cross-model proof, capability/profile cache.
- Phase 6C.1: versioned secret-safe backend/API skeleton and live smoke proof.
- Phase 6C.2: per-camera runtime lifecycle manager and descendant cleanup proof.
- Phase 6C.3: HTTP runtime control API for start/stop/restart.
- Phase 6C.4: HTTP live reprobe, H264/AAC capability refresh, runtime resume and cleanup proof.
- Phase 6C.5: App-owned managed go2rtc publication, two-camera operation and fault-isolated recovery.
- Phase 6C.6: authoritative PPPP availability, persistence/startup policy and three-launch restart proof.

**Phase 6C is complete. Active work starts at Phase 6D — Home Assistant App packaging.**

---

## Phase 6C — App backend/service — COMPLETE

### Phase 6C.1 — Backend state + HTTP API — COMPLETE

Implemented:

- Long-running backend state core.
- `GET /api/v1/health`.
- `GET /api/v1/cameras`.
- `GET /api/v1/cameras/{stable_id}`.
- `GET /api/v1/cameras/{stable_id}/status`.
- `POST /api/v1/discover`.
- Secret-safe capability data.
- Loopback default and bearer-token requirement for non-loopback binding.
- Graceful HTTP shutdown.

Live smoke result: `PHASE6C_API_SMOKE=PASS`.

### Phase 6C.2 — Per-camera runtime lifecycle manager — COMPLETE

Implemented:

- One independent runtime controller per `stable_id`.
- Generic stable-id relay path.
- Stop/restart selected camera only.
- Existing media-stall supervisor behavior preserved.
- Supervisor exit causes lifecycle recreation while desired state remains running.
- Bounded restart backoff.
- Graceful global shutdown stops every managed camera.
- Secret-safe lifecycle state.

Live smoke result: `PHASE6C_LIFECYCLE_SMOKE=PASS`.

### Phase 6C.3 — Runtime control API — COMPLETE

```text
POST /api/v1/cameras/{stable_id}/start
POST /api/v1/cameras/{stable_id}/stop
POST /api/v1/cameras/{stable_id}/restart
```

Implemented idempotent lifecycle behavior, structured state, operation serialization per camera and isolation between different cameras.

### Phase 6C.4 — Reprobe + capability refresh — COMPLETE

Implemented reusable bounded live reprobe, capability cache update only after observed H264 + AAC success, runtime isolation/resume and bounded descendant cleanup.

Live result: `PHASE6C_REPROBE_SMOKE=PASS`.

### Phase 6C.5 — App-owned media publication — COMPLETE

Architecture:

```text
per-camera Lifecycle Manager
        |
        | supervised MPEG-TS stdout
        v
HTTP incoming MPEG-TS ingest
        |
        v
shared App-managed go2rtc
        |
        +--> RTSP /yi_<stable-id-prefix>
        +--> future HA/WebRTC consumer path
        +--> optional Frigate
```

Implemented:

- immutable stream identity from `stable_id`;
- shared managed go2rtc;
- direct lifecycle MPEG-TS push to incoming go2rtc HTTP ingest;
- media-ready producer detection;
- MPEG-TS prebuffer so go2rtc receives a full media probe window;
- camera-only restart/recovery without shared publisher restart;
- two-camera concurrent streams and scoped fault isolation.

Live results:

- `PHASE6C_MEDIA_PUBLISHER_SMOKE=PASS`.
- `PHASE6C_MEDIA_ISOLATION_SMOKE=PASS`.

### Phase 6C.6 — Availability, persistence and startup policy — COMPLETE

#### Authoritative availability

The cloud list is not a live online-state source: all seven cameras returned `online=true` and `state=1`. The YI official-client `PPPP_CheckDevOnline` path produced the exact app UI result:

```text
online_count=4
offline_count=3
unknown_count=0
cloud_hint_disagreement_count=3
PHASE6_ONLINE_STATUS_PROBE=PASS
```

Online: `צד בית`, `מחסן`, `ptz`, `pool`.

Offline: `Living room`, `patio`, `zforce 800`.

`cloud_online_reported` is therefore diagnostic only. New product availability fields are `availability_state`, `availability_source`, `last_online_at` and `availability_error`.

#### Persistent policy

- `start`/`restart` persist `desired_running=true` by immutable `stable_id`.
- `stop` removes the intent.
- Newly discovered cameras default to stopped.
- Desired online cameras are restored after restart.
- Desired offline cameras remain pending and do not create a PPPP/media runtime.
- An already-running desired camera that becomes explicitly offline is stopped while its persistent intent remains.
- `unknown` does not tear down a healthy stream and is not promoted to online.
- Reprobe does not change persistent intent.
- Initial YI cloud failure keeps the service alive and pending intent is retained for retry.

Persistent layout:

```text
/data/capabilities.json
/data/runtime-policy.json
/data/runtime/
/data/publisher/
```

#### Final live proof

The updated persistence smoke passed all regression and live gates:

- 5 persistence/availability tests PASS;
- PTZ + pool dual H264/AAC RTSP PASS;
- offline zforce start deferred with no runtime PASS;
- capability cache under persistent data PASS;
- reprobe preserved intent PASS;
- backend shutdown/restart restored both online desired streams PASS;
- offline zforce remained pending/stopped after restart PASS;
- explicit stop and pending-intent clear persisted PASS;
- third launch restored only PTZ while pool stayed stopped PASS;
- policy cleanup and publisher/service shutdown PASS;
- `PHASE6C_PERSISTENCE_SMOKE=PASS`.

Exit gate: PASS. **Phase 6C is complete.**

---

## Phase 6D — Home Assistant App/Add-on packaging — ACTIVE

Goal: move the proven engine from development infrastructure into an HA OS/Supervisor-managed App with no development-machine paths.

Current official Home Assistant 2026 requirements used by this phase:

- repository root contains `repository.yaml`;
- each App has its own folder with `config.yaml` and Dockerfile;
- Dockerfile uses an explicit `FROM` image (implicit `BUILD_FROM` fallback was removed in Supervisor 2026.04.0);
- `/data` is persistent App storage;
- Home Assistant and Apps communicate on the internal App network;
- `/discovery*` Supervisor API calls are available for App discovery;
- protected mode, AppArmor and least privilege are preferred.

### Phase 6D.1 — Container/runtime packaging — ACTIVE

Initial scaffold implemented:

```text
repository.yaml

yi_home/
  config.yaml
  Dockerfile
  run.sh
  apparmor.txt
  README.md
  DOCS.md
  CHANGELOG.md
  translations/en.yaml
  rootfs/               # generated locally, intentionally gitignored
```

Packaging decisions:

- initial advertised architecture: `amd64` only;
- explicit base: `ghcr.io/home-assistant/base:3.23`;
- runtime packages: Python 3, `py3-cryptography`, FFmpeg/ffprobe, `qemu-aarch64`;
- managed publisher: go2rtc `1.9.14`, downloaded during image build and verified against the known SHA-256 used by the proven Phase 6C path;
- application code path: `/opt/yi-home/app`;
- guest runtime path: `/opt/yi-home/runtime/bionic-root`;
- persistent state: `/data`;
- backend internal port: TCP 8099;
- RTSP: TCP 8554.

`tools/prepare_ha_app_context.py` stages the already-proven development runtime into the App Docker context because a Home Assistant App folder is its build context. It copies top-level Python engine modules, Phase 3 probe/runtime Python helpers and the proven Bionic/native tree. It explicitly refuses/strips development secrets/state such as `.env.local`, backend API tokens, runtime policy and capability state. A secret-safe SHA-256 runtime manifest is generated in the staged image tree.

`tools/phase3_pppp_probe/run_phase6d_app_context_smoke.sh` validates:

- required App files;
- required Bionic/native artifacts;
- no leaked secret/state files;
- no development `~/Documents`/`.analysis` paths in App runtime config;
- no host-network/full-access/Docker-API privileges;
- Supervisor discovery wiring;
- mode-0600 API token persistence wiring;
- authoritative `PPPP_CheckDevOnline` library export;
- staged Python compilation;
- optional actual Docker build with `YI_PHASE6D_DOCKER_BUILD=1`.

Next 6D.1 gates:

1. `PHASE6D_APP_CONTEXT_SMOKE=PASS` on the development machine.
2. Actual amd64 Docker image build PASS.
3. HA OS Local App install/start PASS.
4. Backend health reachable from the App container.
5. Supervisor discovery `yi_home` emitted successfully.
6. AppArmor adjusted only from concrete HA OS audit evidence.

### Phase 6D.2 — Configuration, storage and secrets — PLANNED

Already scaffolded:

- `/run.sh` creates/loads a strong mode-0600 `/data/backend-api-token`.
- Backend binds `0.0.0.0:8099` with bearer authentication because HA Core is a separate container.
- Supervisor discovery payload contains only `host`, internal API port/version/token and RTSP port; it never contains YI account/camera credentials.
- An empty restrictive `/data/yi.env` allows the App/backend to boot before account setup while initial cloud discovery remains pending/retrying.

Still to implement:

- authenticated Integration → App credential-write/reauth API;
- restrictive persistent YI credential store without readback/log exposure;
- account configuration lifecycle and reauthentication semantics;
- token rotation/recovery behavior.

### Phase 6D.3 — Networking and health — PLANNED

Current scaffold:

- no host network;
- no full access;
- no Docker API;
- no Home Assistant config-directory mapping;
- backend API has no host port mapping;
- RTSP 8554 is mapped for optional external consumers;
- custom AppArmor profile exists and will be tightened/refined after first HA OS run.

Still to prove/add:

- HA Core reaches backend over internal App network using Supervisor discovery data;
- add Supervisor watchdog after the packaged health endpoint is proven in HA OS;
- verify shutdown/restart semantics under Supervisor.

### Phase 6D.4 — Architecture support — PLANNED

- Advertise `amd64` only until full container proof passes.
- Verify native/QEMU path independently on `aarch64` before adding it to `config.yaml`.
- Fail clearly on unsupported architectures.

Phase 6D exit gate:

- Fresh HA OS App install starts successfully.
- Integration can configure the YI account through the authenticated internal API.
- Discovery returns account cameras with authoritative availability.
- At least two streams are served directly from the App.
- App restart restores operation.
- No terminal, manual RTSP/YAML or development-machine file paths are required.

---

## Phase 6E — Home Assistant Custom Integration

### Phase 6E.1 — Config Flow

- Consume Supervisor/App discovery through `async_step_hassio`.
- Validate backend API version and health.
- Guide account setup without exposing PPPP/TNP internals.

### Phase 6E.2 — Device Registry

- One HA Device per camera.
- Unique identity based on `stable_id`.
- Camera rename does not create a new device.

### Phase 6E.3 — Entities

- `camera` entity.
- authoritative availability/runtime status.
- optional diagnostic cloud hint.
- restart/reprobe controls where useful.

### Phase 6E.4 — Diagnostics

- App/API version.
- Safe camera metadata.
- Runtime/restart counters.
- Capability/publication/availability state.
- Explicit redaction tests.

Exit gate:

- Add Integration → YI Home creates devices/entities automatically and live view works without YAML.

---

## Phase 6F — Zero-manual-config onboarding

```text
Install YI Home App
  -> Add YI Home Integration
  -> App discovered automatically
  -> enter YI account / region
  -> Found N cameras
  -> Finish
```

No UID/DID/model/TNP/RTSP/YAML required.

---

## Phase 6G — Frigate integration/export

- Stable App-owned RTSP URLs.
- Safe generated example/config helper.
- H264 + AAC recording path.
- Frigate absence/failure never affects core Home Assistant camera support.

---

## Post-product enhancements

- Native timestamp/timebase cleanup.
- More protocol/profile coverage.
- PTZ/camera controls.
- Motion/event integration.
- Reduce/eliminate QEMU where practical.
- Release automation, versioning, App repository and HACS distribution.

## Engineering rule

Every new Phase 6 feature is reusable App/backend functionality first. Development CLIs and shell scripts remain validation adapters and must never become required parts of the final Home Assistant UX.
