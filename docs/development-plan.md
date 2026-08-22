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

Active work starts at **Phase 6C.5 — App-owned media/RTSP publication**.

---

## Phase 6C — App backend/service

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

Live PTZ proof:

- HTTP start reached `running`.
- Native media readers/mux were observed.
- Restart changed lifecycle PID.
- Stop removed the selected runtime.
- Service SIGTERM left no relay descendants.
- `PHASE6C_LIFECYCLE_SMOKE=PASS`.

### Phase 6C.3 — Runtime control API — COMPLETE

```text
POST /api/v1/cameras/{stable_id}/start
POST /api/v1/cameras/{stable_id}/stop
POST /api/v1/cameras/{stable_id}/restart
```

Implemented:

- Idempotent lifecycle behavior.
- `404` for unknown stable IDs.
- Structured runtime state.
- Per-camera operation locks serialize control/reprobe requests for the same camera.
- Different cameras remain independent.

Exit gate: PASS through HTTP-only lifecycle smoke.

### Phase 6C.4 — Reprobe + capability refresh — COMPLETE

Implemented:

- `yi_capability_probe_runtime.py` reusable bounded live-probe core.
- `POST /api/v1/cameras/{stable_id}/reprobe` performs a real live probe.
- Running camera is isolated before reprobe and restored afterward.
- Probe uses the same continuous MPEG-TS stdout path as normal streaming.
- Capability success is based on observed H264 + AAC media, not camera model or relay shutdown timing.
- Capability cache updates atomically only on proof success.
- Previous proven records survive failed probes.
- Probe process groups are bounded and cancelled on App shutdown.
- Secret-safe diagnostics and isolated smoke-test cache.

Live PTZ exit-gate proof (2026-08-23):

- Initial HTTP-started runtime reached native media.
- HTTP reprobe passed on attempt 1.
- Capability source became `addon_api_reprobe`.
- H264 1920x1080 + AAC 16000 Hz mono validated.
- Isolated cache readback passed.
- Runtime resumed with a new PID and reached native media again.
- Stop, graceful shutdown and probe cleanup passed.
- `PHASE6C_REPROBE_SMOKE=PASS`.

### Phase 6C.5 — App-owned media publication — ACTIVE

Goal: remove all dependency on user-maintained development go2rtc stream definitions while preserving backend ownership of PPPP/TNP lifecycle.

Architecture locked for the first implementation:

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

Why incoming MPEG-TS is used:

- go2rtc officially supports incoming MPEG-TS through `/api/stream.ts?dst=...`.
- An incoming producer is not created/owned by go2rtc; the external App controls when it starts/stops.
- This preserves Phase 6C.2 lifecycle ownership and self-healing semantics.
- go2rtc remains one shared long-lived publisher and is not restarted for an individual camera restart.

Implementation now in progress:

- `yi_stream_identity.py` — immutable media stream names derived only from `stable_id`.
- `yi_media_publisher.py` — managed shared go2rtc process and generated empty-stream configuration.
- Lifecycle manager can push supervised MPEG-TS directly to the managed publisher using chunked HTTP streaming.
- Backend exposes secret-safe publication metadata alongside camera/runtime state.
- Service accepts explicit managed-go2rtc binary/API/RTSP settings while keeping publisher disabled for older development smoke tests unless requested.
- `tools/phase3_pppp_probe/run_phase6c_media_publisher_smoke.sh` provides the first isolated PTZ proof on non-production ports.

Stable media identity:

```text
stable_id:   e2f22804fecdbd8c3561
stream:      yi_e2f22804fecd
RTSP path:   /yi_e2f22804fecd
```

Display-name changes therefore never change media URLs or Home Assistant identity.

6C.5A exit gate — isolated publisher proof:

- Start a separate backend + managed go2rtc on non-production ports.
- Generated publisher contains all discovered camera destinations.
- Start PTZ through backend HTTP.
- Lifecycle reports media publisher attached and byte growth.
- RTSP endpoint validates H264 1920x1080 + AAC 16 kHz mono.
- Restart PTZ and prove the shared go2rtc PID does not change.
- RTSP becomes valid again after the per-camera runtime restart.
- App/service shutdown removes the managed go2rtc process.

6C.5B final exit gate — multi-camera isolation:

- Two App-managed streams operate concurrently.
- Force-stall one selected camera.
- Only that camera lifecycle generation changes.
- Shared publisher PID and second camera runtime remain unchanged.
- Both RTSP endpoints validate H264 + AAC after recovery.

### Phase 6C.6 — Backend persistence and startup policy — NEXT

Requirements:

- Persist non-secret runtime preferences and capability cache under App `/data`.
- Decide/implement automatic startup policy for discovered cameras.
- Restore intended runtime state after App restart.
- Safe behavior when YI cloud is temporarily unavailable at boot.
- Structured diagnostics for lifecycle/publication failures.

Exit gate:

- Backend restart restores camera inventory/runtime policy without manual configuration.

Phase 6C is complete only after 6C.1–6C.6 pass.

---

## Phase 6D — Home Assistant App/Add-on packaging

Goal: move the engine from development infrastructure into HA OS/Supervisor.

### 6D.1 Container/runtime packaging

- App repository/folder structure.
- `config.yaml`, Dockerfile, startup script and AppArmor profile.
- Explicit reproducible Docker base image.
- Python backend and native runtime included.
- QEMU/libPPPP/FFmpeg/go2rtc packaged explicitly.
- No development-machine paths.
- Initial architecture target `amd64`; add `aarch64` only after proof.

### 6D.2 Configuration, storage and secrets

- Persistent `/data` capability/runtime state.
- App-generated internal backend API token stored mode 0600 under `/data`.
- Supervisor discovery passes only internal API connection metadata/token to the Integration.
- YI credentials never appear in discovery/logs/read APIs/diagnostics.
- Integration sends YI account credentials through authenticated internal API.

### 6D.3 Networking and health

- `host_network: false`.
- No `full_access`, Docker API or Home Assistant config-directory mapping.
- Backend API internal to the App network.
- RTSP host exposure only when required for external consumers.
- Supervisor watchdog tied to backend health.

### 6D.4 Architecture support

- Verify packaged native/QEMU path on each advertised architecture.
- Fail clearly on unsupported architecture.

Exit gate:

- Fresh HA OS App install starts successfully.
- Discovery returns account cameras.
- At least two streams are served directly from the App.
- App restart restores operation.

---

## Phase 6E — Home Assistant Custom Integration

### 6E.1 Config Flow

- Consume Supervisor/App discovery through `async_step_hassio`.
- Validate backend API version and health.
- Guide account setup without exposing PPPP/TNP internals.

### 6E.2 Device Registry

- One HA Device per camera.
- Unique identity based on `stable_id`.
- Camera rename does not create a new device.

### 6E.3 Entities

- `camera` entity.
- runtime/connectivity status.
- cloud-online state.
- restart/reprobe controls where useful.

### 6E.4 Diagnostics

- App/API version.
- Safe camera metadata.
- Runtime/restart counters.
- Capability/publication state.
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
