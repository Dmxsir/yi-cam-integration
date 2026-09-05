# YI Home Integration – Development Plan

This document tracks the implementation order and exit gates for the remaining product work.

Target architecture remains fixed:

- **YI Home App/Add-on = engine/runtime**
- **YI Home Custom Integration = Home Assistant UI/device/entity layer**
- **Frigate = optional downstream media consumer**

Development laptop services and hand-edited go2rtc configuration are validation infrastructure only; they are not the final deployment design.

See also [`home-assistant-app-requirements.md`](home-assistant-app-requirements.md) and the current checkpoint [`checkpoints/2026-08-23-phase6d3-haos-live-stream.md`](checkpoints/2026-08-23-phase6d3-haos-live-stream.md).

## Current position

Completed:

- Phase 1–2: cloud/APK/TNP research.
- Phase 3: phone-free native PPPP/TNP H264 + AAC media.
- Phase 4: Frigate interoperability.
- Phase 5: multi-camera operation and self-healing supervisor.
- Phase 6A: generic account discovery by secret-safe `stable_id`.
- Phase 6B: generic runtime path, cross-model proof and capability cache.
- Phase 6C: long-running App backend/service, lifecycle, managed go2rtc, availability and persistence.
- Phase 6D.1: Home Assistant App/container packaging and HA OS Local App bootstrap.
- Phase 6D.2: authenticated Integration → App account handoff and persistent secret storage.
- Phase 6D.3 one-camera HA OS live media: PASS after isolating and fixing the FFmpeg 8 regression.
- Home Assistant Integration foundation: Supervisor discovery, account flow, 7 camera Devices and 21 status/control entities live in HA OS.

**Active gate: Phase 6D.3 multi-camera HA OS E2E and restart isolation.**

---

## Phase 6C — App backend/service — COMPLETE

The reusable engine is complete enough for product packaging:

- versioned secret-safe HTTP API;
- account discovery and inventory;
- one supervised native PPPP/TNP runtime per `stable_id`;
- start/stop/restart APIs;
- bounded live reprobe and capability refresh;
- one shared managed go2rtc publisher;
- stable App-owned stream identity;
- two-camera publication and scoped recovery proof;
- authoritative `PPPP_CheckDevOnline` availability;
- durable desired-running policy;
- persistent `/data` capability/runtime/publisher state.

Live regression gates:

```text
PHASE6C_API_SMOKE=PASS
PHASE6C_LIFECYCLE_SMOKE=PASS
PHASE6C_REPROBE_SMOKE=PASS
PHASE6C_MEDIA_PUBLISHER_SMOKE=PASS
PHASE6C_MEDIA_ISOLATION_SMOKE=PASS
PHASE6C_PERSISTENCE_SMOKE=PASS
```

Exit gate: PASS.

---

## Phase 6D — Home Assistant App/Add-on packaging — ACTIVE

Goal: run the proven engine as an HA OS/Supervisor-managed App with no development-machine dependency.

### Phase 6D.1 — Container/runtime packaging — COMPLETE

Implemented/proven:

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
  rootfs/               # generated locally, gitignored
```

Runtime/security decisions:

- `amd64` initial advertised architecture;
- explicit `ghcr.io/home-assistant/base:3.23` base;
- Python 3 + cryptography;
- `qemu-aarch64` for the proven native worker path;
- managed go2rtc `1.9.14` with pinned SHA-256;
- application path `/opt/yi-home/app`;
- Bionic/native guest root `/opt/yi-home/runtime/bionic-root`;
- persistent App state `/data`;
- backend TCP 8099 only on the internal App network;
- optional RTSP TCP 8554 exposure;
- protected/AppArmor operation without host network/full access/Docker API.

`tools/prepare_ha_app_context.py` stages only the proven engine/native runtime and rejects development secrets/state.

`tools/phase3_pppp_probe/run_phase6d_app_context_smoke.sh` validates App artifacts, security constraints, Python compilation, native availability exports, secret-safe staging and the actual Docker image when enabled.

HA OS Local App is proven as:

```text
slug=local_yi_home
source=/addons/yi_home
protected=true
host_network=false
full_access=false
docker_api=false
```

Issue #2 vendor bootstrap was also validated end to end on real HAOS at
`81dd900`:

```text
Issue #2 HAOS bootstrap validation: PASS
Issue #2 persistence validation: PASS
Issue #2 end-to-end media validation: PASS
```

The first start imported the official user-supplied APK from
`/share/yi_rtsp/yi-home.apk`; an App restart reused the validated private
`/data/vendor/libPPPP_API.so`, the backend and five managed runtimes recovered,
HA discovery republished, and all camera live streams were visible again. The
required Local App deployment order is `copy local App` → `ha store reload` →
`ha apps rebuild local_yi_home` → `ha apps start local_yi_home` because rebuild
alone can reuse stale Supervisor Local App metadata.

No APK or `libPPPP_API.so` is tracked or packaged, `/share` remains read-only,
and no protected PPPP/media/runtime behavior changed. The stale Dockerfile
assertion that required the private library inside the image was a packaging
bug fixed in `81dd900`.

Exit gate: PASS.

### Phase 6D.2 — Configuration, storage and secrets — COMPLETE

Implemented/proven:

- mode-0600 `/data/backend-api-token` generated/reused by the App;
- bearer authentication required for the non-loopback backend bind;
- Supervisor discovery carries only internal App connection information;
- authenticated `GET /api/v1/account` and `POST /api/v1/account`;
- account login/device-list validation before persistence;
- atomic restrictive `/data/yi.env` persistence;
- YI password never stored in HA Config Entry;
- cloud session tokens and raw camera connection material never returned by account/status APIs;
- account state and initial discovery survive App restart;
- no implicit auto-start of every discovered camera.

The Home Assistant Config Flow now performs the account handoff directly through the authenticated App API.

Exit gate: PASS.

### Phase 6D.3 — Networking, health and live media — ACTIVE

Already proven:

- Home Assistant Core consumes Supervisor/App discovery;
- Integration reaches App backend on the internal App network;
- account configuration works from HA UI;
- 7 camera Devices and 21 entities are registered;
- Stream switch starts/stops durable App runtime intent;
- Online and Runtime entities expose secret-safe state;
- one-camera HA OS live stream is stable.

#### FFmpeg 8 regression — RESOLVED

The original HA OS live test repeatedly stalled after roughly 20–30 seconds with lifecycle exit code `75`.

The fault was reproduced in the exact App image outside Home Assistant. This ruled out HA Core, Supervisor, AppArmor, Integration polling and Frigate as the primary cause.

A/B isolation:

```text
Alpine + QEMU 8.2.2 + FFmpeg 8.0.1 = FAIL after roughly 20–30 s
Alpine + QEMU 8.2.2 + FFmpeg 6.0.1-static = PASS for 60 s
```

The full backend/lifecycle/go2rtc pipeline using the normal App QEMU 10.1.5 plus FFmpeg 6.0.1-static passed 150 seconds with:

```text
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes=22020096
```

Therefore QEMU is not the root cause.

Packaging fix:

- remove Alpine's unpinned `ffmpeg` package from the App runtime;
- pin FFmpeg and ffprobe `6.0.1-static`;
- verify archive SHA-256 during build;
- install binaries under `/usr/local/bin`;
- enforce exact FFmpeg/ffprobe version in Phase 6D App-context Docker smoke.

Build gate after the fix:

```text
pinned_ffmpeg_runtime=PASS
docker_ffmpeg_pin=PASS
docker_build=PASS
PHASE6D_APP_CONTEXT_SMOKE=PASS
```

#### One-camera HA OS live E2E — COMPLETE

After rebuilding `local_yi_home` with the pinned FFmpeg runtime, the `ptz` camera remained stable:

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

This closes the one-camera live-stream gate.

#### Next live gate — multi-camera HA OS E2E

Run the following proof without changing product architecture:

1. Keep `ptz` running.
2. Enable `pool` from its Home Assistant Stream entity.
3. Observe both runtimes for at least 3–5 minutes.
4. Require for both:

```text
desired_running=true
process_alive=true
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes increasing
```

5. Stop or restart exactly one camera and prove the other camera remains running with unchanged restart count/generation.
6. Require the shared go2rtc process to remain alive and unchanged.
7. Restart the App and prove only persisted desired-running + authoritative-online cameras are restored.
8. Re-check both runtime entities after restoration.

If all eight gates pass, mark Phase 6D.3 multi-camera/restart behavior PASS.

### Phase 6D.4 — Architecture support — PLANNED

- Keep `amd64` only for the initial product.
- Prove the full native/QEMU/media path independently on `aarch64` before advertising it.
- Fail clearly on unsupported architectures.

### Phase 6D exit gate

Require all of the following:

- fresh HA OS App install/start;
- Integration-driven account setup;
- automatic inventory and HA device/entity registration;
- at least two simultaneous App-owned live streams;
- independent stream lifecycle behavior;
- App restart restores persisted desired-running online streams;
- no terminal/manual UID/DID/model/RTSP/YAML/Android dependency in normal product use.

---

## Phase 6E — Home Assistant Custom Integration — ACTIVE

Implementation began in parallel with Phase 6D because the HA OS packaging/security gates require the real Integration path.

### Phase 6E.1 — Config Flow — FOUNDATION COMPLETE

Implemented/proven:

- `async_step_hassio` consumes YI Home Supervisor discovery;
- backend health/API validation;
- App-required fallback for manual invocation;
- region/account form;
- authenticated account handoff;
- HA Config Entry excludes YI password.

Remaining:

- final reauthentication/error UX.

### Phase 6E.2 — Device Registry — COMPLETE FOR CURRENT INVENTORY

- one HA Device per camera;
- immutable identity derived from secret-safe camera identity;
- 7 devices live-registered.

### Phase 6E.3 — Status/control entities — FOUNDATION COMPLETE

Currently live:

- authoritative Online binary sensor;
- Runtime status sensor with safe lifecycle attributes;
- Stream switch controlling App start/stop intent;
- 3 entities per camera, 21 total for the current account.

Remaining:

- camera/live-view entity backed by the App-owned media path;
- polished translations/entity names;
- dynamic device additions without reload where practical;
- additional controls only where they remain generic and safe.

### Phase 6E.4 — Diagnostics — ACTIVE

Keep diagnostics limited to safe information:

- API/App version;
- stable secret-safe camera metadata;
- availability/runtime state;
- restart counters;
- publication state;
- explicit redaction tests.

Never expose YI passwords, camera passwords, cloud/session tokens, App bearer tokens, UID/DID, PPPP InitString or raw connection material.

Phase 6E exit gate:

- Add YI Home Integration automatically creates camera devices/entities and live camera view without YAML or PPPP/TNP internals.

---

## Phase 6F — Zero-manual-config onboarding

Target flow:

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

Only after the App-native media lifecycle is proven on HA OS:

- consume stable App-owned RTSP URLs from Frigate;
- validate H264 + AAC recording/detection path;
- provide a safe generated configuration/export helper later;
- Frigate absence/failure must never affect core App/Integration runtime.

---

## Post-product enhancements

- native timestamp/timebase cleanup;
- more protocol/profile coverage;
- PTZ/camera controls;
- motion/event integration;
- reduce/eliminate QEMU where practical;
- release automation/versioning/App repository/HACS distribution.

## Engineering rule

Every new Phase 6 feature must remain reusable App/backend/Integration functionality. Development CLIs and shell scripts are validation adapters only and must never become required parts of the final Home Assistant UX.
