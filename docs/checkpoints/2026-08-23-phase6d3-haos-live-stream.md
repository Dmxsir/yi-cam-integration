# Checkpoint — 2026-08-23 — Phase 6D.3 HA OS live-stream investigation

## Status

- Phase 6D.1 App/container packaging: **COMPLETE**.
- HA OS Local App bootstrap: **COMPLETE**.
- Phase 6D.2 Integration → App account credential handoff and restart persistence: **COMPLETE**.
- Home Assistant device/entity registration: **PASS** — 7 cameras, 3 entities per camera (21 entities total).
- Phase 6D.3 short-run one-camera HA OS media: **PASS**.
- Exact pinned image 10-minute host-network long-run: **PASS**.
- Exact pinned image 10-minute Docker bridge/NAT long-run: **PASS**.
- HA OS one-camera AppArmor-enabled long-run: **FAIL** — observed `exit=75` and `exit=1` runtime recreation.
- HA OS one-camera AppArmor-disabled 10-minute A/B: **PASS**.
- **Current root-cause direction: AppArmor policy restriction strongly isolated; exact missing rule still pending.**
- Multi-camera HA OS gate remains blocked until the restrictive profile is corrected and re-proven.

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

A full backend/lifecycle/go2rtc test with the normal App QEMU 10.1.5 and FFmpeg 6.0.1-static passed 150 seconds with `restart_count=0` and continuous publication. FFmpeg 8.0.1 remains excluded; the App pins FFmpeg/ffprobe 6.0.1-static by SHA-256.

## HA OS failure evidence with AppArmor profile enabled

After the FFmpeg pin, PTZ initially streamed successfully but longer operation produced runtime recreation. Observed outcomes included:

```text
restart_count=3
last_exit_code=75
last_reason=recreated_after_exit
publisher_attached=true
publisher_error=null
```

and later:

```text
restart_count=2
last_exit_code=1
publisher_attached=true
publisher_error=null
```

Exit `75` is the media-stall watchdog. Exit `1` is a relay/native/mux failure path. The old `ValueError: read of closed file` traceback in App logs belongs to a prior deployment before the publisher shutdown-race fix and is not current evidence.

## Exact pinned image long-run outside HA OS

### Host networking — PASS

600-second PTZ run:

```text
generation=1
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes=93192192
```

### Docker bridge/NAT — PASS

Second 600-second PTZ run using normal Docker bridge networking:

```text
generation=1
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes=81264640
producer_registered=true
producer_media_ready=true
publisher_ready=true
```

Runtime log showed PPPP connect/auth success, `media_started=true`, and uninterrupted MPEG-TS progress through more than 80 MB.

These two tests rule out the pinned image, FFmpeg 6.0.1, QEMU 10.1.5, ordinary Docker bridge/NAT, lifecycle, persistence, availability polling and shared go2rtc as the primary cause.

## HA OS read-only evidence

No correlated YI-specific AppArmor denial, OOM kill or cgroup throttling event was obtained from the available HA OS logs. A previously pasted `dmesg` capture was later identified as development-laptop output and was therefore not used as HA OS evidence.

Because audit collection may not expose every denied operation in the available shell environment, a controlled one-variable AppArmor A/B was performed.

## HA OS AppArmor-disabled one-camera A/B — PASS

The local App source was changed temporarily from:

```text
apparmor: true
```

to:

```text
apparmor: false
```

After local App rebuild/start, Supervisor reported:

```text
apparmor: disable
state: started
```

All other important variables were intentionally preserved: same HA OS host, same App image/runtime, same FFmpeg 6.0.1, same QEMU 10.1.5, same bridge networking, same backend/lifecycle/go2rtc path and PTZ only.

Observed immediately after stream start:

```text
State: running
Desired: True
Process: True
Restarts: 0
Reason: started
Exit: None
Publisher: True
Bytes: 23461888
Error: None
```

Observed after roughly ten minutes:

```text
State: running
Desired: True
Process: True
Restarts: 0
Reason: started
Exit: None
Publisher: True
Bytes: 80150528
Error: None
```

No runtime recreation occurred during the diagnostic window and publication bytes continued increasing.

## Current conclusion

The evidence now strongly isolates the restrictive AppArmor profile as the HA OS-specific failure source:

- AppArmor profile enabled on HA OS: repeated long-run runtime recreation (`75` and `1`).
- Same HA OS App with AppArmor disabled: stable for roughly ten minutes, restart count 0, continuous publication.
- Same exact image outside HA OS: stable for 600 seconds under both host networking and Docker bridge/NAT.

This does **not** justify shipping with AppArmor disabled. The product target remains protected, least-privilege operation. The next step is to identify the smallest missing AppArmor permission, restore `apparmor: true`, and prove long-run stability again.

## Next isolation gate — AppArmor rule narrowing

Current profile already allows broad file access plus IPv4/IPv6 stream and datagram sockets, but does not allow other network families generically and contains no capability grants.

First diagnostic should preserve AppArmor enforcement while temporarily broadening only the network mediation class:

```text
network,
```

If a 10-minute HA OS PTZ run becomes stable with AppArmor enabled + broad network permission, narrow that broad rule toward the actual extra network family/type required by the native PPPP runtime (likely a non-INET control/introspection socket such as netlink, pending proof).

If AppArmor enabled + broad `network,` still fails, restore the original network rules and test the next AppArmor class separately rather than shipping a broad profile.

Do not proceed to multi-camera HA OS testing until AppArmor is re-enabled and the corrected restrictive profile passes long-run one-camera validation.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString or raw camera connection material.
