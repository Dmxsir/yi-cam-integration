# Checkpoint — 2026-08-23 — Phase 6D.3 HA OS live-stream investigation

## Status

- Phase 6D.1 App/container packaging: **COMPLETE**.
- HA OS Local App bootstrap: **COMPLETE**.
- Phase 6D.2 Integration → App account credential handoff and restart persistence: **COMPLETE**.
- Home Assistant device/entity registration: **PASS** — 7 cameras, 3 entities per camera (21 entities total).
- Phase 6D.3 short-run one-camera HA OS media: **PASS**.
- Exact pinned image 10-minute host-network long-run on development host: **PASS**.
- Exact pinned image 10-minute Docker bridge/NAT long-run on development host: **PASS**.
- HA OS one-camera long-run: **FAIL / ACTIVE INVESTIGATION**.
- Multi-camera HA OS gate: **BLOCKED**.

## Proven media/runtime baseline

The App remains pinned to FFmpeg/ffprobe 6.0.1-static and QEMU 10.1.5. The earlier Alpine FFmpeg 8.0.1 20–30 second stall was independently reproduced and fixed by the FFmpeg pin.

The exact pinned image subsequently passed two 600-second development-host runs using the full persistent backend/lifecycle/native relay/shared-go2rtc path and no RTSP consumer:

```text
Docker host networking:
  generation=1
  restart_count=0
  last_exit_code=null
  published_bytes=93192192

Docker bridge/NAT:
  generation=1
  restart_count=0
  last_exit_code=null
  published_bytes=81264640
```

Ordinary Docker bridge/NAT is therefore ruled out.

## HA OS failure evidence

On HA OS the PTZ runtime repeatedly recreates after apparently healthy publication. `published_bytes` is generation-local and resets on recreation; current-generation `publisher_attached=true` does not describe the previous generation's failure.

Structured diagnostics progressively narrowed two independent failure paths:

```text
95 = malformed/corrupt AAC unit validation
76 = post-start media stall while both QEMU/native worker and FFmpeg remain alive
103 = same qemu+ffmpeg-alive stall, specifically while the relay is blocked writing H.264 into FFmpeg
```

The AAC path was fixed by treating isolated malformed channel-1 packets as recoverable and dropping only that packet. After deployment, `95` stopped being the observed failure and the remaining instability consistently followed the media-stall path.

## AAC recovery fix

`yi_native_av_relay.py` raises `AudioUnitValidationError` for packet-level audio validation failures. The continuous live loop drops only that isolated audio record and continues. Session/config invariants remain fatal.

Safe logs expose only a count:

```text
audio_validation_drop_count=<n>; action=drop_and_continue
```

Relevant commits:

```text
58cdef37  Tolerate isolated malformed AAC units in live relay
4effefa7  Test recoverable malformed AAC unit handling
```

## AppArmor — ruled out

Repeated A/B tests with enforcing, broadened rules, complain-style experiments, and `apparmor: false` did not correlate with stability. AppArmor is not the root cause. The product stays on the normal restrictive profile.

## Child liveness and blocking-stage diagnostics

The supervisor first depended on `/proc` for descendant state, which was unavailable on HA OS at the critical moment. A relay-owned `0600` marker now reports only fixed safe fields from direct process handles. The first useful result was:

```text
exit=76
```

This proved both QEMU/native worker and FFmpeg were still alive while MPEG-TS had stopped for the 12-second watchdog interval.

A second refinement added one allowlisted relay blocking stage. The resulting long HA OS run produced:

```text
restart_count=48
last_exit_code=103
```

after more than one hour of PTZ-only testing.

`103` means:

```text
QEMU/native worker: alive
FFmpeg: alive
relay blocking point: video_pipe.write(H264 -> FFmpeg)
```

This is strong evidence of **live FFmpeg input backpressure / cross-stream deadlock**, not a crashed process, startup failure, AppArmor issue, Docker NAT issue, or generic PPPP termination.

## Interleave-bound A/B — failed to resolve 103

A targeted A/B kept the existing architecture but added this live-only FFmpeg option:

```text
-max_interleave_delta 500000
```

The finite validation/file path remained unchanged. The intent was to prevent a delayed/sparse audio stream from allowing long mux interleave buffering.

Result: **FAIL as a fix**. Over the following hour the PTZ runtime accumulated 48 restarts and the latest structured exit remained `103`.

Therefore lowering mux interleave delay alone is insufficient. The root design problem is that the Python relay feeds both FFmpeg inputs from one thread: once the H.264 pipe blocks, that same thread cannot continue consuming native media or feed an AAC packet that FFmpeg may require before draining more video.

Relevant commits for the failed interleave A/B:

```text
8ab5631c  Bound live FFmpeg interleave buffering after video pipe stalls
a1a16841  Test bounded live FFmpeg interleave command
```

## Current fix under test — independent FFmpeg input writers

The stable-id live adapter now keeps the 500 ms interleave bound but decouples the two FFmpeg input pipes behind independent daemon writer threads:

```text
native relay main loop
  -> video queue -> dedicated H.264 writer -> FFmpeg video pipe
  -> audio queue -> dedicated AAC writer  -> FFmpeg audio pipe
```

The main native relay no longer blocks directly in `video_pipe.write()` or `audio_pipe.write()` during live stdout publication. A blocked video writer therefore cannot prevent AAC from reaching FFmpeg, and a blocked audio writer cannot prevent H.264 from being consumed from the native PPPP stream.

Important properties:

- live/stdout path only;
- finite validation/file path unchanged;
- no media packets intentionally dropped;
- writer failures surface back to the existing safe exception classifier on subsequent producer writes;
- blocked writer state remains visible to the existing secret-safe watchdog marker;
- no PID, command line, camera identity, media payload or credential is persisted in diagnostics.

Relevant commits:

```text
dee48d80  Decouple live FFmpeg video and audio pipe writers
e7e3e2af  Test independent live FFmpeg input writers
```

## Current diagnostic codes

```text
74 = startup stall before first MPEG-TS bytes
75 = post-start media stall; process state unavailable
76 = qemu + ffmpeg alive; stage unavailable
77 = qemu alive, ffmpeg missing
78 = qemu missing, ffmpeg alive
79 = qemu + ffmpeg missing
81 = native worker exited non-zero
82 = FFmpeg mux exited non-zero
83 = zero video frames
84 = zero audio frames
85 = other relay exception
86 = safely unclassified relay failure
87 = relay EOFError
88 = relay RuntimeError
89 = subprocess timeout
90 = BrokenPipeError
91 = OSError
92 = ValueError
93 = native header/framing failure
94 = invalid native media record
95 = AAC unit validation
96 = AAC format changed
97 = H.264 validation
98 = worker pipe setup failure
100 = qemu+ffmpeg alive; waiting for native header
101 = qemu+ffmpeg alive; waiting for native payload
102 = qemu+ffmpeg alive; blocked writing AAC to FFmpeg
103 = qemu+ffmpeg alive; blocked writing H.264 to FFmpeg
104 = qemu+ffmpeg alive; mux startup
105 = qemu+ffmpeg alive; packet processing
```

## Next gate

1. Keep `apparmor: true` and PTZ-only scope.
2. Deploy `dee48d80` + `e7e3e2af` after local syntax/unit tests pass.
3. Restart the App and enable PTZ only.
4. Target at least 30 minutes with `restart_count=0`; continue to 60 minutes if clean.
5. If a restart occurs, record the structured exit immediately. A repeated `103` after async writers would mean FFmpeg is not merely waiting for the other input; then the next A/B should isolate video-only vs audio+video rather than adding more timing knobs.
6. Do not resume the two-camera HA OS gate until one-camera long-run stability is proven.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString, raw connection material, raw per-camera runtime logs, exception messages, process command lines or PIDs.
