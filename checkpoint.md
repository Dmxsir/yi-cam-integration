# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-08-26_  
_Branch: `phase-3-linux-pppp`  
_Repository: `Dmxsir/yi-cam-integration`

## Purpose

Canonical handoff/context document for continuing the YI camera reverse-engineering / Home Assistant project after context loss or in a new chat.

**Mandatory workflow:** every repository source change must also update this `checkpoint.md` with current source state, deployment state, evidence, conclusions and next step.

## User workflow constraint

1. Assistant edits GitHub directly.
2. User gets at most **one laptop command**.
3. User gets at most **one Home Assistant command**.
4. If one side needs no command, say so.
5. Do not send another command until the current result is reported.
6. Do not ask the user to edit/commit/push source locally when the assistant can update GitHub directly.

Canonical paths:

```text
Laptop checkout: ~/Documents/yi-cam-integration-phase3
HA OS host:       10.0.0.16
HA integration:   /config/custom_components/yi_home
HA App context:   /addons/yi_home
App slug:         local_yi_home
```

Public names:

```text
App:         YI RTSP
Integration: YI Camera Connect
```

Internal identifiers remain `yi_home`.

## High-level architecture

```text
YI camera
 -> PPPP/TNP native session
 -> AArch64 native worker under QEMU
 -> H264 + AAC native records
 -> Python relay
 -> FFmpeg MPEG-TS mux
 -> App-owned go2rtc / RTSP
 -> HA OS mapped host RTSP port
 -> external Frigate
```

The App owns camera runtime lifecycle and go2rtc publication. Frigate is only a consumer.

## Completed Phase 6G — Frigate integration/export

Phase 6G is complete and must not be reopened absent a real regression.

Stable source:

```text
rtsp://<HA-host>:<mapped-port>/yi_<stable-prefix>
```

Known PTZ example:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

Mapped RTSP host port is Supervisor-discovered, not hardcoded.

Previously validated:

- live video
- live audio
- detection
- recording
- stream OFF/ON lifecycle
- secret-safe Frigate export
- App-owned go2rtc publication

Do **not** start Phase 6E while the restart/stall issue below is unresolved.

## Relevant runtime IDs

```text
e2f22804fecd = PTZ front camera
867ecdee5a36 = pool
6a046d860b2d = separate unstable camera
```

Do not invent other friendly-name mappings without evidence.

## TNP/PPPP two-stage startup — proven and deployed

Official capture:

```text
T+~3 ms      9029 no.2  use-count=1
              768 no.3

T+~5928 ms   9029 no.11 use-count=2
              768 no.12
```

Commands:

```text
4881 = SET_RESOLUTION
4882 = response
9029 = START_REALTIME
768  = START_AUDIO
767  = STOP_LIVE
```

Implementation:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

Worker staging helper:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

Validated worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

Do not add blind extra `9029` requests.

## Native worker exits

```text
40 = PPPP_Connect negative
50 = initial PPPP_Write failure
60 = first channel-0 PPPP_Read failed / not exactly 8 bytes
61/62/63 = response framing/body/auth failure
71 = media thread creation failure
72 = media reader failure
73 = refresh thread creation failure
```

Observed negative connection value:

```text
0xFFFFF445 = signed -3003
```

Its semantic meaning is unproven.

## Supervisor stall / exit codes

```text
74  = startup stall: zero MPEG-TS bytes in 45 s
75  = generic media stall
81  = native worker failure propagated by stable wrapper
88  = relay runtime error
100 = native_header_wait after media started
101 = native_payload_wait
102 = audio_pipe_write
103 = video_pipe_write
104 = mux_starting
105 = relay_processing
```

Startup timeout is 45 s; post-start stall timeout 12 s. Do not increase as workaround.

## App staging rule

`yi_home/Dockerfile`:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

Therefore:

- root Python change => `python3 tools/prepare_ha_app_context.py`, then copy staged file into `/addons/yi_home/rootfs/...`, then rebuild App;
- `yi_home/run.sh` can be copied directly and needs rebuild;
- native C change => compile/stage worker;
- never assume a root Python change is already inside the App context.

## Graceful shutdown

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

Supervisor first SIGTERMs relay parent so relay can send STOP/BREAK/FORCECLOSE and close PPPP cleanly. Process-group TERM/KILL is fallback after grace timeout.

PTZ usually exits gracefully; `6a046d860b2d` sometimes requires process-group fallback.

## Safe diagnostics policy

`yi_home/run.sh` mirrors only fixed allowlisted prefixes from `/data/runtime/*.log`.

Allowed evidence:

- PPPP return codes
- TNP response metadata/auth result
- native channel counters
- fixed relay/supervisor stages
- H264 NAL type/count/size metadata
- MPEG-TS byte counts
- fixed FFmpeg state markers

Never expose arbitrary FFmpeg/worker stderr, command lines, credentials, DID/device keys/tokens, raw media or secret-bearing environment values.

## Channel semantics

```text
channel1 = AAC audio records
channel2 = I-frame video records
channel3 = P-frame video records
```

## Historical diagnostics

### Minimal FFmpeg probing

```text
328fd031caaee8a13b4b74bc2234f57cb9895874
```

Live probing reduced to video `probesize=4096/analyzeduration=0/fpsprobesize=0`, audio `probesize=1024/analyzeduration=0`. PTZ still stalled. Large probe windows are not root cause.

### First H264 NAL diagnostic

```text
b3fa9d06c9e976447f5f3570d3915f14331c953d
```

Failed PTZ generations still show:

```text
first_video_nal_types=7,8,5
SPS=1 PPS=1 IDR=1
```

Missing SPS/PPS/IDR is not primary Class-A cause.

### First-five H264 record-shape diagnostic

```text
d412e35ef0134c4b83e312aca425e6dde7189b70
0d4a6437843864d16beee3d945977567afc72577
5fc8df9d764903f7ac3d4aea18a6044123f18a00
```

Successful and failed sessions can begin with the same several P records (`NAL 1`) before an I record (`7,8,5`). Stable cameras can also do this. Do not inject AUD without new evidence.

## FFmpeg state diagnostics — decisive evidence

Commits:

```text
daa6ec85306676ec130656702077c840d8ccaaa5  safe FFmpeg state wrapper
dbafcdc62df3c09f7e90db9b89d701afd00e12a1  App activation/allowlist
29fa6489c7af4cf6edcdaaf564fa731685361cd0  checkpoint
```

Failed PTZ Class-A startup reaches all of:

```text
ffmpeg_state=diagnostic_active
ffmpeg_state=video_input_open
ffmpeg_state=video_stream_info
ffmpeg_state=audio_input_open
ffmpeg_state=audio_stream_info
ffmpeg_state=output_mpegts_ready
ffmpeg_state=stream_mapping_ready
```

Then remains silent for 45 s. On SIGTERM the first MPEG-TS chunk appears immediately and mux/worker can exit cleanly.

Therefore Class A is **after both inputs are opened/identified and MPEG-TS output/mapping are ready, but before first output packet is emitted**.

Strongly ruled out for Class A:

- no P-frames
- no SPS/PPS/IDR
- large probing window
- failure to identify H264
- failure to identify AAC
- failure to create MPEG-TS output
- failure to map streams

Leading area remains FFmpeg packet scheduling / A-V interleave / timestamp behavior.

## PTZ independent failure classes

Do not collapse these into one bug.

### Class A — FFmpeg post-init startup stall

```text
TNP auth PASS
media readers STARTED
I/P/audio present
mpegts_mux=STARTED
all FFmpeg state milestones reached
45 s zero TS
exit 74
SIGTERM
first TS appears immediately
```

Target of current A/B experiment.

### Class B — no initial I-frame

Observed:

```text
channel1_records=28
channel2_records=0
channel3_records=37
video_frames=0
```

Exclude from Class-A A/B judgment.

### Class C — native worker exit 60

```text
native_worker_exit=60
relay_exit_rc=81
```

Early PPPP/TNP failure; separate from Class A. Exclude from A/B judgment.

### Class D — post-start native header starvation

After successful publication PTZ can later hit code 100 `qemu_alive_ffmpeg_alive_native_header_wait`. Separate source/session starvation state.

## `6a046d860b2d` independently unstable

Observed:

- startup 74
- post-start 100 native-header wait
- 102 audio-pipe write stall
- worker 60
- occasional process-group TERM/KILL

Do not treat all `6a` failures as PTZ root cause.

## Current temporary A/B — PTZ MPEG-TS video-only output

Goal: test whether mapped AAC/A-V interleave causes Class A while AAC input remains consumed so the relay audio writer cannot block merely because of the test.

### Experiment behavior when activated

For PTZ live only:

- H264 input unchanged;
- AAC input remains open and consumed;
- remove output `-map 1:a:0` only;
- remove `-bsf:a` because audio is not mapped;
- H264 stream-copy, no transcoding;
- MPEG-TS output becomes video-only;
- PPPP/TNP, worker, two-stage 9029/768, reorder and watchdogs unchanged.

Activation marker:

```text
ffmpeg_state=ptz_video_only_ab_active
```

Shutdown summary must report:

```text
video_only=1
```

Other cameras remain `video_only=0`.

### A/B detection history

```text
8db7d48162fee17b89e4b78bc247f7004a066ad6  direct-parent detection
0fecfe106b5f06c17901e3eb4658aeb8927d3ed6  bounded ancestor cmdline scan
3f34ee8d657127aa9e7fccaa4e96c9db6ef45899  self stderr runtime-log detection
198f5154d598678ecd5d15a6d4e3be431397c830  hardened self+ancestor stderr/cmdline detection + safe detector marker
```

The first three deployed detection approaches did **not** activate the A/B in HA. Every valid PTZ FFmpeg shutdown summary stayed:

```text
video_only=0
```

and no `ptz_video_only_ab_active` appeared. These runs are therefore **not A/B results**; they only reconfirm the normal A/V Class-A failure.

### Latest deployed evidence — 15:05 local, 2026-08-26

The App rebuilt/restarted successfully and normal FFmpeg diagnostics were active.

PTZ first produced a separate Class-C generation:

```text
native_worker_exit=60
relay_exit_rc=81
```

Then a valid Class-A generation showed:

```text
TNP auth PASS
media readers STARTED
first_video_nal_types=7,8,5
all FFmpeg input/output/mapping milestones
startup_stall exit 74
channel1_records=59
channel2_records=1
channel3_records=61
first TS only after SIGTERM
video_only=0
```

A later valid Class-A generation again showed all milestones, exit 74, first TS on SIGTERM and `video_only=0`.

Therefore `3f34ee8d...` self-fd2 detection also did **not** activate in the actual HA process topology.

The same log again showed `6a046d860b2d` independent issues including channel2=0 startup and post-start code100.

## Current source — hardened PTZ detector

Commit:

```text
198f5154d598678ecd5d15a6d4e3be431397c830
```

Changed file:

```text
yi_ffmpeg_state_wrapper.py
```

The wrapper now performs bounded secret-safe detection in this order:

1. its own stderr FD target basename;
2. each ancestor's stderr FD target basename, up to 8 ancestors;
3. each ancestor's exact `--stable-id e2f22804fecd` pair as fallback.

Runtime log basename matching tolerates Linux ` (deleted)` suffix.

It exposes one fixed marker only:

```text
ffmpeg_state=ptz_detection=self_stderr
ffmpeg_state=ptz_detection=ancestor_stderr
ffmpeg_state=ptz_detection=ancestor_cmdline
ffmpeg_state=ptz_detection=none
```

No path, PID or command-line contents are logged.

Any detector other than `none` activates video-only and also emits:

```text
ffmpeg_state=ptz_video_only_ab_active
```

This commit is diagnostic plus the already-approved PTZ-only A/B behavior; it does not change TNP, worker, codecs, timeouts or other cameras.

### Interpretation

If valid PTZ `video_only=1` generations produce TS promptly/reliably, evidence points to mapped AAC, A/V timestamp relationship or A/V interleave/output scheduling.

If valid PTZ `video_only=1` generations still reach video output readiness then stall until EOF, mapped AAC is not sufficient; next focus is H264 timing/SETTS/video mux scheduling.

If detector reports `none`, do not interpret A/B behavior. Use that marker to choose the next deterministic targeting mechanism rather than guessing.

Exclude channel2=0 and worker60 generations from the A/B verdict.

## Current deployment state

- Normal FFmpeg state diagnostics deployed and proven.
- H264 shape diagnostics deployed and proven.
- `8db7d481...`, `0fecfe106...`, and `3f34ee8d...` were deployed but did not activate A/B (`video_only=0`).
- Hardened detector commit `198f5154...` is **in GitHub and not yet confirmed deployed**.
- No worker rebuild required.
- `run.sh` unchanged; all `ffmpeg_state=` lines are already allowlisted.

## Next step

Deploy only updated root-level `yi_ffmpeg_state_wrapper.py`:

1. laptop: pull, `py_compile`, prepare App context, copy staged wrapper to HA App context;
2. HA: rebuild/restart `local_yi_home`;
3. first inspect PTZ `ffmpeg_state=ptz_detection=...`;
4. if source is not `none`, require `ptz_video_only_ab_active` and later `video_only=1` before judging A/B;
5. collect several valid Class-A generations;
6. exclude channel2=0 and worker60 generations.

## Do not do next

- Do not start Phase 6E.
- Do not increase timeouts.
- Do not add blind retries/additional 9029.
- Do not inject AUD yet.
- Do not reopen solved Frigate networking/audio/export.
