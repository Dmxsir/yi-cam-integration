# Checkpoint — 2026-08-23 — Phase 6D.3 HA OS live-stream investigation

## Status

- Phase 6D.1 App/container packaging: **COMPLETE**.
- HA OS Local App bootstrap: **COMPLETE**.
- Phase 6D.2 Integration → App account credential handoff and restart persistence: **COMPLETE**.
- Home Assistant device/entity registration: **PASS** — 7 cameras, 3 entities per camera (21 entities total).
- Phase 6D.3 short-run one-camera HA OS media: **PASS**.
- **Phase 6D.3 long-run one-camera HA OS media: FAIL / ACTIVE INVESTIGATION.**
- Multi-camera HA OS gate: **BLOCKED** until the long-run one-camera stall is resolved.

## Architecture at this checkpoint

```text
YI Home App
  cloud discovery / persistent account state
  PPPP availability
  per-camera native PPPP/TNP runtime
  H264 + AAC relay
  shared App-managed go2rtc

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

## FFmpeg 8 short-run regression — isolated and fixed

The first HA OS stream attempts with Alpine 3.23 FFmpeg 8.0.1 stalled after roughly 20–30 seconds. The same failure was reproduced outside Home Assistant using the exact App image.

Isolation A/B:

```text
Alpine + QEMU 8.2.2 + FFmpeg 8.0.1 = FAIL around 25–30 s
Alpine + QEMU 8.2.2 + FFmpeg 6.0.1-static = PASS for 60 s
```

A full backend/lifecycle/go2rtc test with the normal App QEMU 10.1.5 and FFmpeg 6.0.1-static passed 150 seconds:

```text
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes=22020096
```

Therefore the 20–30 second regression was specific to FFmpeg 8.0.1, not QEMU.

The App Dockerfile now pins FFmpeg/ffprobe 6.0.1-static with a fixed archive SHA-256 instead of installing Alpine's unpinned `ffmpeg` package. Build smoke verifies the exact pinned version.

## HA OS short-run proof after FFmpeg pin

After rebuilding `local_yi_home`, PTZ initially remained healthy long enough to publish more than 31 MB:

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

This proved the FFmpeg 8 short-run regression was removed, but it was **not sufficient to close the long-run live-stream gate**.

## New long-run failure evidence

Keeping the same PTZ stream enabled longer produced:

```text
desired_running=true
process_alive=true
restart_count=3
last_reason=recreated_after_exit
last_exit_code=75
publisher_attached=true
published_bytes=2228224
publisher_error=null
```

`published_bytes` is generation-local and is reset when a new runtime generation is launched, so the lower value is expected after recreation.

Exit code `75` is emitted by `yi_native_session_supervisor.py` only when no relay stdout bytes arrive for the configured startup/stall window. For an already-started stream this means at least 12 seconds without new MPEG-TS bytes, followed by termination/recreation of the relay process group.

`publisher_error=null` on the current generation does not indicate a go2rtc failure. The immediate fact is that the supervised relay stopped producing stdout bytes long enough to trigger the media-stall watchdog.

## Corrected conclusion

- FFmpeg 8.0.1 definitely caused an early 20–30 second stall and must remain excluded.
- FFmpeg 6.0.1 fixes that early regression.
- A second, longer-duration stall still exists and is **not yet isolated**.
- The previous 150-second validation window was too short to prove long-run stability.
- Phase 6D.3 one-camera E2E is therefore **not complete**.

## Next isolation gate

Before enabling a second HA camera, run the exact pinned `yi-home:phase6d` image on the development laptop for at least 10 minutes using the full persistent backend/lifecycle/shared-go2rtc path and production 12-second stall watchdog, with no RTSP consumer.

Interpretation:

- If the pinned exact image also recreates with `exit=75`, the remaining issue is below HA/Supervisor and must be isolated inside the native relay / FFmpeg 6 / camera-session path.
- If the pinned exact image stays `restart_count=0` for 10 minutes while HA OS recreates, focus next on HA OS container/runtime constraints, scheduling, networking or App-specific environment.

Only after one camera remains stable for a materially longer window should the multi-camera HA OS gate resume.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString or raw camera connection material.
