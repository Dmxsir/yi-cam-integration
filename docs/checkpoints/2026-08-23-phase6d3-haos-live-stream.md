# Checkpoint — 2026-08-23 — Phase 6D.3 HA OS live-stream investigation

## Status

- Phase 6D.1 App/container packaging: **COMPLETE**.
- HA OS Local App bootstrap: **COMPLETE**.
- Phase 6D.2 Integration → App account credential handoff and restart persistence: **COMPLETE**.
- Home Assistant device/entity registration: **PASS** — 7 cameras, 3 entities per camera (21 entities total).
- Phase 6D.3 short-run one-camera HA OS media: **PASS**.
- Exact pinned image 10-minute host-network long-run: **PASS**.
- Exact pinned image 10-minute Docker bridge/NAT long-run: **PASS**.
- HA OS one-camera restrictive AppArmor profile: **FAIL** — observed `exit=75` and repeated `exit=1` runtime recreation.
- HA OS one-camera AppArmor-disabled 10-minute run: **PASS once; correlation is strong but not yet sufficient to identify policy as root cause.**
- Broad AppArmor A/Bs for `network,`, `signal,`, and combined `unix,` + `capability,` + `ptrace,`: **FAIL** with `exit=1`.
- AppArmor complain-flag experiment: **FAIL** with repeated `exit=1`; no useful audit events were exposed through available HA OS logs.
- **Current root cause remains HA OS/App-environment specific. Stop rule guessing; improve safe runtime failure observability and re-confirm the AppArmor-disabled correlation with a longer repeat run.**
- Multi-camera HA OS gate remains blocked.

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

## HA OS failure evidence with restrictive AppArmor profile

After the FFmpeg pin, PTZ initially streamed successfully but longer operation produced runtime recreation. Observed outcomes included watchdog `exit=75` and repeated relay/native/mux path `exit=1`.

`published_bytes` is generation-local and resets after recreation. `publisher_error=null` on a new generation does not identify the prior failing layer.

The old `ValueError: read of closed file` traceback in App logs belongs to a prior deployment before the publisher shutdown-race fix and is not current evidence.

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

These tests strongly rule out ordinary Docker host-vs-bridge networking and the pinned FFmpeg/QEMU/application stack as the short-horizon cause.

## HA OS AppArmor-disabled A/B — PASS once

The local App source was changed temporarily from `apparmor: true` to `apparmor: false`. Supervisor reported:

```text
apparmor: disable
state: started
```

PTZ then remained stable for roughly ten minutes:

```text
restart_count=0
last_exit_code=null
publisher_attached=true
publisher_error=null
published_bytes=80150528
```

This is a strong correlation with AppArmor state, but subsequent policy-broadening tests did not reproduce the same stability. Therefore it is no longer sufficient to state that one missing AppArmor rule has been isolated.

## AppArmor policy-broadening tests — FAIL

With AppArmor enforcing, each of the following diagnostics still produced runtime recreation with `exit=1`:

```text
network,
```

then, after restoring the original network rules:

```text
signal,
```

then, after restoring the clean profile again:

```text
unix,
capability,
ptrace,
```

The combined `unix + capability + ptrace` test failed quickly with `restart_count=1`, `last_exit_code=1`.

A profile `complain` flag experiment also continued to recreate repeatedly (`restart_count=4`, `last_exit_code=1`) and exposed no useful AppArmor audit events through `core-ssh`, host logs, or Supervisor logs.

## Corrected conclusion

- FFmpeg 8.0.1 was a real, independently reproduced early-stall bug and remains fixed by pinning FFmpeg 6.0.1-static.
- The exact pinned image is stable for at least 600 seconds outside HA OS under both host and bridge networking.
- HA OS continues to show `exit=1`/`75` recreations under the restrictive AppArmor profile.
- One AppArmor-disabled 10-minute run passed, but broadening the obvious AppArmor rule classes did not reproduce that stability.
- Therefore the current evidence does **not** justify continuing to guess individual AppArmor rules or declaring a specific AppArmor class the root cause.
- The next engineering priority is safe failure observability inside the App runtime so `exit=1` can be classified as native worker, MPEG-TS mux, supervisor, publisher, or relay exception without exposing secrets.
- In parallel, repeat the AppArmor-disabled run for a materially longer window to determine whether the prior 10-minute PASS is reproducible or stochastic.

## Next isolation gate

1. Restore a known clean AppArmor profile for normal enforcing tests.
2. Add secret-safe lifecycle diagnostics derived only from allowlisted runtime log markers, for example:
   - `last_failure_stage`
   - `last_native_worker_exit`
   - `last_mux_exit`
   - `last_supervisor_exit`
   - `last_failure_at`
3. Preserve the prior failure cause across runtime recreation instead of overwriting it immediately with `recreated_after_exit`.
4. Expose those fields through backend safe status and the HA Runtime status sensor.
5. Rebuild/redeploy, reproduce one HA OS `exit=1`, and use the new fields to choose the next isolation test.
6. Separately repeat AppArmor-disabled PTZ for at least 20–30 minutes before treating the earlier 10-minute PASS as causal.

Do not proceed to multi-camera HA OS testing until one-camera failure classification and long-run stability are proven.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString or raw camera connection material.
