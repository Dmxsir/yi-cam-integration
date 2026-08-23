# Checkpoint — 2026-08-23 — Phase 6D.3 HA OS live-stream proof

## Status

- Phase 6D.1 App/container packaging: **COMPLETE**.
- HA OS Local App bootstrap: **COMPLETE**.
- Phase 6D.2 Integration → App account credential handoff and restart persistence: **COMPLETE**.
- Home Assistant device/entity registration: **PASS** — 7 cameras, 3 entities per camera (21 entities total).
- **Phase 6D.3 one-camera HA OS live-stream E2E: PASS / COMPLETE.**
- Phase 6D.3 multi-camera HA OS live-stream gate: **NEXT**.
- Phase 6D overall: **ACTIVE** until multi-camera App proof and restart/consumer gates are complete.

## Architecture at this checkpoint

```text
YI Home App
  cloud discovery / persistent account state
  PPPP availability
  per-camera native PPPP/TNP runtime
  H264 + AAC relay
  shared App-managed go2rtc
        |
        +--> stable RTSP publication

YI Home Custom Integration
  Supervisor/App discovery
  account setup
  one HA Device per camera
  Online / Runtime / Stream entities

Frigate
  optional downstream RTSP consumer
```

No Android phone, ADB, SD-card hack, manual UID/DID/model selection, per-camera YAML or manual RTSP setup is part of the target Home Assistant user flow.

## HA OS packaging/runtime state

Local App:

```text
slug=local_yi_home
source=/addons/yi_home
arch=amd64
protected=true
host_network=false
full_access=false
docker_api=false
backend_port=8099 (internal App network)
go2rtc_rtsp_port=8554 (optional host mapping)
```

The App starts from persistent `/data`, reuses the mode-0600 backend API token, preserves account configuration and discovers the account inventory after restart without starting every camera automatically.

## FFmpeg 8 media-stall regression — root cause isolated

The first HA OS one-camera live-stream test repeatedly failed after startup with lifecycle exit code `75` and media stalls. The failure was reproduced outside Home Assistant using the exact App image, ruling out HA Core, Supervisor, AppArmor, HA polling and Frigate as the primary cause.

Observed failing pattern with Alpine 3.23 FFmpeg 8.0.1:

```text
media starts successfully
MPEG-TS bytes advance to roughly 0.7–1.4 MiB
output stops advancing after roughly 20–30 seconds
runtime remains present until watchdog detects 12 s silence
exit=75 / recreate
```

Isolation results:

1. Same native runtime and go2rtc version on the development laptop outside the App image remained stable.
2. Exact App image reproduced the stall with no RTSP consumer.
3. File-output mode also stalled, ruling out lifecycle HTTP ingest/go2rtc as the cause.
4. Replacing QEMU 10.1.5 with static QEMU 8.2.2 did **not** change the failure.
5. Keeping Alpine + native runtime + QEMU and replacing only FFmpeg 8.0.1 with FFmpeg 6.0.1-static fixed the stream.

A/B proof:

```text
Alpine + QEMU 8.2.2 + FFmpeg 8.0.1  = FAIL around 25–30 s
Alpine + QEMU 8.2.2 + FFmpeg 6.0.1  = PASS for 60 s
```

Full production media-path proof with the App backend/lifecycle/shared go2rtc and FFmpeg 6.0.1-static:

```text
runtime=running
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes: 0 -> 22,020,096 over 150 s
```

This full-path test used the normal App QEMU 10.1.5, therefore the QEMU version is not the root cause.

## Packaging fix

The App Dockerfile no longer installs Alpine's unpinned `ffmpeg` package.

Pinned runtime:

```text
FFmpeg 6.0.1-static
FFprobe 6.0.1-static
QEMU 10.1.5
Go2rtc 1.9.14
```

The FFmpeg archive version and SHA-256 are pinned during the Docker build, and the Phase 6D App-context smoke checks that the image actually reports `ffmpeg version 6.0.1-static` and `ffprobe version 6.0.1-static`.

Build proof:

```text
secret_files_copied=false
PHASE6D_APP_CONTEXT_PREPARE=PASS
required_app_artifacts=PASS
build_context_secret_scan=PASS
development_paths_removed=PASS
app_security_config=PASS
pinned_ffmpeg_runtime=PASS
startup_policy_wiring=PASS
restart_persistence_markers=PASS
online_status_runtime_packaged=PASS
staged_python_compile=PASS
docker_ffmpeg_pin=PASS
docker_build=PASS
production_modified=false
PHASE6D_APP_CONTEXT_SMOKE=PASS
```

Image verification:

```text
ffmpeg version 6.0.1-static
ffprobe version 6.0.1-static
qemu-aarch64 version 10.1.5
```

## HA OS deployment proof

The rebuilt `local_yi_home` App was deployed from `/addons/yi_home` with the pinned FFmpeg runtime. Existing persistent account/App state was retained.

One-camera HA OS live proof (`ptz`) after deployment:

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

There was no media-stall recreation and no publisher error. This closes the one-camera Phase 6D.3 live-stream regression gate.

## Security / secret handling

The checkpoint intentionally contains no YI password, camera password, cloud token, App bearer token, UID/DID, PPPP InitString or raw connection material.

Persistent account credentials remain App-owned under `/data`; the Home Assistant Config Entry does not contain the YI password. Camera/runtime identities exposed to the Integration remain stable secret-safe IDs and friendly metadata.

## Next live gate — multi-camera HA OS E2E

Keep the proven `ptz` stream running and enable one additional authoritative-online camera, initially `pool`.

Require both camera runtimes to remain concurrently stable for at least 3–5 minutes:

```text
desired_running=true
process_alive=true
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes increasing
```

Then verify:

1. both streams remain independently published by the shared App go2rtc;
2. stopping/restarting one stream does not restart or disturb the other camera or shared publisher;
3. App restart restores only cameras with persisted `desired_running=true` and authoritative-online state;
4. after the App-native multi-camera gate passes, validate optional downstream RTSP consumption from Frigate without making Frigate part of the core App lifecycle.

Do not mark Phase 6D complete until the multi-camera HA OS gate and restart behavior are proven.
