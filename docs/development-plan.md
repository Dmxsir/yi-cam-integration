# YI Home Integration – Development Plan

This document expands the high-level roadmap into the implementation order and exit gates for the remaining product work.

The target architecture remains fixed:

- **YI Home Add-on = engine/runtime**
- **YI Home Custom Integration = Home Assistant UI/device/entity layer**
- **Frigate = optional media consumer**

Development laptop services and hand-edited go2rtc configuration are validation infrastructure only; they are not the final deployment design.

## Current position

Completed:

- Phase 1–2: cloud/APK/TNP research.
- Phase 3: phone-free native PPPP/TNP H264 + AAC media.
- Phase 4: Frigate interoperability.
- Phase 5: multi-camera operation and self-healing supervisor.
- Phase 6A: generic account discovery by secret-safe `stable_id`.
- Phase 6B: generic runtime path, cross-model proof, capability/profile cache.
- Phase 6C.1: versioned secret-safe Add-on backend/API skeleton and live smoke proof.

Active work starts at **Phase 6C.2**.

---

## Phase 6C — Add-on backend/service

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

### Phase 6C.2 — Per-camera runtime lifecycle manager — ACTIVE

Goal: make the Add-on backend, not go2rtc preload configuration, own the lifetime of each supervised PPPP/TNP runtime.

Implementation requirements:

- One independent runtime controller per `stable_id`.
- Start a camera through the generic stable-id relay path.
- Stop only the selected camera and its descendants.
- Restart only the selected camera.
- Preserve the existing media-stall supervisor behavior.
- If the supervisor exits because of a stall, the lifecycle manager recreates that camera runtime.
- Bounded restart delay/backoff to prevent hot restart loops.
- Graceful global shutdown stops every managed camera.
- No camera secrets in lifecycle status or logs produced by the API.

Runtime states:

```text
stopped
starting
running
restarting
stopping
error
```

Exit gate:

- Start a non-production camera by `stable_id` through the service.
- Confirm a live supervised native process exists.
- API status reports `running`.
- Restart changes the runtime process without affecting other cameras.
- Stop removes the runtime cleanly.
- Service SIGTERM leaves no relay/QEMU/FFmpeg descendants.

### Phase 6C.3 — Runtime control API — NEXT

API operations:

```text
POST /api/v1/cameras/{stable_id}/start
POST /api/v1/cameras/{stable_id}/stop
POST /api/v1/cameras/{stable_id}/restart
```

Requirements:

- Idempotent start/stop behavior.
- `404` for unknown `stable_id`.
- Structured state returned after each operation.
- Concurrent requests for one camera serialized safely.
- One camera failure does not block other camera API operations.

Exit gate:

- Start/status/restart/stop smoke test passes through HTTP only.

### Phase 6C.4 — Reprobe + capability refresh — NEXT

Goal: make `POST /api/v1/cameras/{stable_id}/reprobe` a real operation.

Requirements:

- Stop or isolate the selected runtime safely when required.
- Run bounded live capability/profile probe.
- Validate observed H264/AAC media.
- Atomically update capability cache only on proof success.
- Preserve previous proven cache record if the new probe fails.
- Return secret-safe probe result and failure category.
- Resume prior runtime state after reprobe when appropriate.

Exit gate:

- HTTP reprobe updates `observed_at` for a known camera and the camera resumes streaming.

### Phase 6C.5 — Add-on-owned media publication — NEXT

Goal: remove dependency on manually maintained development go2rtc stream definitions.

Requirements:

- Media publisher is started/configured by the Add-on service.
- Stable endpoint derives from immutable `stable_id`, not display name.
- Friendly camera name remains metadata only.
- H264/AAC is forwarded without unnecessary transcoding.
- Publisher survives/rebinds after a camera runtime restart.
- Per-camera RTSP URL is exposed in the secret-safe backend API.
- A camera stall/restart does not restart the entire media publisher.

Target form:

```text
rtsp://<addon-host>:8554/yi_<stable-id-prefix>
```

The exact publisher implementation may use embedded/managed go2rtc initially, provided ownership belongs to the Add-on and no user YAML is required.

Exit gate:

- Two Add-on-managed camera streams run concurrently.
- Force-stalling one camera causes only that camera to recover.
- Both RTSP endpoints validate with H264 + AAC after recovery.

### Phase 6C.6 — Backend persistence and startup policy — NEXT

Requirements:

- Persist non-secret runtime preferences and capability cache under Add-on `/data`.
- Decide/implement automatic startup policy for discovered cameras.
- Restore intended camera runtime state after Add-on restart.
- Safe behavior when YI cloud is temporarily unavailable at boot.
- Structured diagnostics for camera lifecycle failures.

Exit gate:

- Backend restart restores camera inventory/runtime policy without manual configuration.

Phase 6C is complete only after 6C.1–6C.6 pass.

---

## Phase 6D — Home Assistant Add-on packaging

Goal: move the engine from the development laptop into a real HA OS/Supervisor Add-on.

### 6D.1 Container/runtime packaging

- Add-on directory structure.
- Dockerfile/build definition.
- Python backend and native runtime included.
- QEMU/libPPPP/FFmpeg/go2rtc strategy packaged explicitly.
- Runtime paths no longer depend on development checkout layout.

### 6D.2 Add-on configuration and secrets

- Account/region configuration through Add-on options or Integration handoff.
- Secrets stored using the Add-on/Supervisor environment, never exposed through diagnostics.
- Persistent `/data` for capability cache and runtime state.

### 6D.3 Networking and health

- Internal API port.
- RTSP port.
- Healthcheck tied to `/api/v1/health`.
- Authentication/network boundary suitable for HA Supervisor networking.

### 6D.4 Architecture support

- Primary target: architecture used by the existing HA OS installation.
- Document/test multi-architecture strategy for native ARM library/QEMU requirements.
- Fail clearly on unsupported architecture rather than silently misbehaving.

Exit gate:

- Fresh Add-on install on HA OS starts successfully.
- Account discovery returns all cameras.
- At least two camera streams are available directly from the Add-on.
- Restarting the Add-on restores operation.

---

## Phase 6E — Home Assistant Custom Integration

Goal: provide the normal Home Assistant user experience while keeping native/runtime complexity in the Add-on.

### 6E.1 Config Flow

- Discover/connect to the YI Home Add-on.
- Validate API version and health.
- Guide account setup without exposing internal PPPP/TNP settings.

### 6E.2 Device Registry

- One HA Device per camera.
- Unique identity based on `stable_id`.
- Camera rename in YI does not create a new HA device.

### 6E.3 Entities

Initial entities:

- `camera` entity.
- connectivity/runtime state sensor.
- cloud-online sensor/attribute.
- capability/profile diagnostic sensor or diagnostic data.
- restart/reprobe buttons/services where useful.

### 6E.4 Diagnostics

- Add-on/API version.
- Camera safe metadata.
- Runtime state/restart counters.
- Capability state.
- Explicit redaction tests for all secrets.

Exit gate:

- Add Integration → YI Home creates devices/entities automatically from the Add-on inventory.
- Live camera view works without user YAML.

---

## Phase 6F — Zero-manual-config onboarding

Target user flow:

```text
Install YI Home Add-on
  -> Add YI Home Integration
  -> enter YI account / region
  -> automatic discovery
  -> Found N cameras
  -> Finish
```

Requirements:

- No UID/DID/raw model/TNP version/RTSP URL required from the user.
- No per-camera YAML.
- Helpful handling of temporarily offline cameras.
- Clear unsupported-camera reporting only after capability probes fail.

Exit gate:

- Fresh installation can be completed from the HA UI without terminal access.

---

## Phase 6G — Frigate integration/export

Frigate remains optional.

Requirements:

- Stable Add-on-owned RTSP URLs.
- Documentation/example config generated from safe camera metadata.
- H264 video + AAC audio recording path.
- Frigate failure or absence never affects core HA camera support.

Exit gate:

- Add-on stream can be added to Frigate without changing YI runtime code.

---

## Post-product enhancements

These are intentionally after the basic installable product works:

- Native timestamp/timebase cleanup.
- More protocol/profile coverage.
- PTZ and other camera controls where supported.
- Motion/event integration.
- Reduce/eliminate QEMU where technically practical.
- Release automation, versioning, Add-on repository distribution and HACS distribution for the Integration.

## Engineering rule

Every new Phase 6 feature must be implemented first as reusable Add-on/backend functionality. Development CLIs and shell scripts are test adapters only and must not become required parts of the final Home Assistant user experience.
