# Checkpoint — 2026-08-23 — Phase 6D.3 HA OS live-stream investigation

## Status

- Phase 6D.1 App/container packaging: **COMPLETE**.
- HA OS Local App bootstrap: **COMPLETE**.
- Phase 6D.2 Integration → App account credential handoff and restart persistence: **COMPLETE**.
- Home Assistant device/entity registration: **PASS** — 7 cameras, 3 entities per camera (21 entities total).
- Phase 6D.3 short-run one-camera HA OS media: **PASS**.
- **Phase 6D.3 long-run one-camera HA OS media: FAIL / ACTIVE INVESTIGATION.**
- Exact pinned image 10-minute host-network long-run: **PASS**.
- Multi-camera HA OS gate: **BLOCKED** until the HA OS-specific long-run stall is isolated.

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

## HA OS long-run failure evidence

Keeping the same PTZ stream enabled longer produced runtime recreations including:

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

Later two-camera observation also showed relay exits with `last_exit_code=1` on both PTZ and pool, while current generations could continue publishing. Therefore two distinct observed failure outcomes exist: watchdog media-stall recreation (`75`) and relay/native/mux failure (`1`).

`published_bytes` is generation-local and resets when a new runtime generation is launched.

Exit code `75` is emitted by `yi_native_session_supervisor.py` when no relay stdout bytes arrive for the configured startup/stall window. For an already-started stream this means at least 12 seconds without new MPEG-TS bytes, followed by termination/recreation of the relay process group.

The old `ValueError: read of closed file` traceback visible in App logs belongs to a previous deployment before the publisher shutdown-race fix and is not evidence for the current failure.

## Exact pinned image 10-minute long-run — PASS

The exact current `yi-home:phase6d` image was tested on the development laptop using:

- FFmpeg 6.0.1-static;
- QEMU 10.1.5;
- full persistent backend;
- production lifecycle manager and 12-second stall watchdog;
- shared managed go2rtc;
- PTZ only;
- no RTSP consumer;
- Docker `--network host`.

Result over 600 seconds:

```text
restart_count=0 for every sample
last_exit_code=null
generation=1
process_alive=true
publisher_attached=true
publisher_error=null
published_bytes=93192192
producer_registered=true
producer_media_ready=true
publisher_ready=true
```

`published_bytes` increased monotonically from 1,572,864 at 15 seconds to 93,192,192 at 600 seconds. No runtime recreation occurred.

This is strong evidence that the pinned application image, FFmpeg 6 runtime, QEMU 10.1.5, lifecycle manager, native relay and go2rtc can remain stable for at least ten minutes outside HA OS.

## Current conclusion

- FFmpeg 8.0.1 definitely caused the early 20–30 second stall and remains excluded.
- FFmpeg 6.0.1 fixes that regression.
- The exact pinned image is stable for at least 600 seconds on the development laptop with host networking.
- HA OS still shows longer-run runtime recreation.
- The remaining fault is therefore narrowed to an environmental difference between the successful laptop run and the HA OS App execution.
- The most important unisolated difference is networking: the successful laptop test used Docker host networking, while the HA OS App deliberately runs with `host_network=false` behind the Home Assistant App bridge/NAT.
- Resource scheduling/cgroup/AppArmor or HA OS-specific runtime constraints remain possible only if bridge networking is ruled out.

## Next isolation gate — Docker bridge networking A/B

Before changing the Home Assistant App privilege model, run the exact same pinned image on the development laptop for at least 10 minutes **without `--network host`**, using normal Docker bridge/NAT. Keep backend/go2rtc internal to the container and inspect status through `docker exec`.

Interpretation:

- If the bridge-mode container recreates with `exit=75` or `exit=1`, networking/NAT becomes the leading root cause and the next proof should compare PPPP behavior with host networking versus bridge networking directly.
- If bridge mode also remains `restart_count=0` for 10 minutes, Docker bridge/NAT is ruled out on the development host and the investigation moves to HA OS-specific App constraints (Supervisor networking implementation, resource/cgroup scheduling, AppArmor or host kernel/runtime differences).

Do not enable a second HA camera until the one-camera HA OS-specific difference is isolated.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString or raw camera connection material.
