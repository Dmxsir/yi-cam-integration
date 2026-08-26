# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-08-26_  
_Branch: `phase-3-linux-pppp`  
_Repository: `Dmxsir/yi-cam-integration`

## Purpose

This is the canonical handoff/context document for continuing the YI camera reverse-engineering / Home Assistant project in a new ChatGPT chat or after context loss.

**Mandatory workflow rule:** every repository source change must also update this `checkpoint.md` with current code state, deployment state, evidence, conclusions and next step.

## User workflow constraint

The user wants a minimal deployment/troubleshooting workflow:

1. Assistant edits GitHub directly.
2. User gets at most **one command for the laptop**.
3. User gets at most **one command for Home Assistant**.
4. If one side needs no command, say so.
5. Do not send another command until the current command result is reported.
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

Phase 6G is complete and must not be reopened unless there is a real regression.

Stable Frigate source:

```text
rtsp://<HA-host>:<mapped-port>/yi_<stable-prefix>
```

Known PTZ example:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

The mapped host port is discovered through Supervisor and is not hardcoded in production code.

Previously validated:

- live video
- live audio
- detection
- recording
- stream OFF/ON lifecycle
- secret-safe Frigate export
- App-owned go2rtc publication

Do **not** start Phase 6E while the restart/stall problem below is unresolved.

## Relevant camera runtime IDs

```text
e2f22804fecd = PTZ front camera
867ecdee5a36 = pool
6a046d860b2d = separate unstable camera
```

Do not guess other stable-ID/friendly-name mappings without evidence.

## TNP/PPPP two-stage startup — proven and deployed

The official client capture proves a two-stage start:

```text
T+~3 ms      9029 no.2  use-count=1
              768 no.3

T+~5928 ms   9029 no.11 use-count=2
              768 no.12
```

Relevant commands:

```text
4881 = SET_RESOLUTION
4882 = response
9029 = START_REALTIME
768  = START_AUDIO
767  = STOP_LIVE
```

Implementation commit:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

Worker build/staging helper:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

Validated deployed worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

Do not add more blind `9029` retries. The current two-stage pattern is capture-proven.

## Native worker exit meanings

```text
40 = PPPP_Connect returned negative
50 = initial PPPP_Write failure
60 = first channel-0 PPPP_Read failed / did not return exactly 8 bytes
61/62/63 = response framing/body/auth failure
71 = media thread creation failure
72 = media reader failure
73 = second-stage refresh thread creation failure
```

Observed connection value:

```text
0xFFFFF445 = signed -3003
```

Its semantic meaning is not proven. Do not label it timeout/already-connected/etc.

## Supervisor stall/exit codes

```text
74  = startup stall: no MPEG-TS bytes inside 45 s
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

Startup timeout is 45 s. Post-start media stall timeout is 12 s.

Do not increase these timeouts as a workaround.

## App build/staging rule

`yi_home/Dockerfile` copies generated rootfs and `run.sh`:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

Therefore:

- root-level Python changes require `python3 tools/prepare_ha_app_context.py` before copying the staged file into `/addons/yi_home/rootfs/...`;
- `yi_home/run.sh` can be copied directly to `/addons/yi_home/run.sh` and requires App rebuild;
- native C changes require worker compile/stage;
- do not assume root-level Python changes reach the App automatically.

## Graceful shutdown

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

The supervisor first SIGTERMs the relay parent so the relay can request STOP/BREAK/FORCECLOSE and close PPPP cleanly. Process-group SIGTERM/SIGKILL is only fallback after the grace period.

PTZ usually exits cleanly after watchdog termination. `6a046d860b2d` sometimes still needs process-group fallback.

## Safe diagnostics policy

`yi_home/run.sh` mirrors only fixed allowlisted prefixes from `/data/runtime/*.log` into the visible App log.

Safe information includes:

- PPPP return codes
- TNP response version/command/auth result
- native channel counters
- fixed relay/supervisor stages
- H264 NAL type/count/size metadata
- MPEG-TS byte counts
- fixed FFmpeg state markers

Never expose arbitrary FFmpeg stderr, worker stderr, command lines, credentials, DIDs, device keys, tokens, raw video/audio bytes or secret-bearing environment values.

## Channel semantics

Established from diagnostics:

```text
channel1 = AAC audio records
channel2 = I-frame video records
channel3 = P-frame video records
```

## Important historical diagnostics

### Minimal probing experiment

Commit:

```text
328fd031caaee8a13b4b74bc2234f57cb9895874
```

Live FFmpeg probing was reduced to:

```text
video probesize       4096
video analyzeduration 0
video fpsprobesize    0
audio probesize       1024
audio analyzeduration 0
```

Result: PTZ startup stalls continued. Therefore large stream-info probe windows are not the root cause.

### First H264 NAL diagnostic

Commit:

```text
b3fa9d06c9e976447f5f3570d3915f14331c953d
```

Failed PTZ generations still showed:

```text
first_video_nal_types=7,8,5
first_video_has_sps=1
first_video_has_pps=1
first_video_has_idr=1
```

Therefore missing SPS/PPS/IDR is not the main startup cause.

### First-five-record H264 shape diagnostic

Commits:

```text
d412e35ef0134c4b83e312aca425e6dde7189b70  record-shape logging
0d4a6437843864d16beee3d945977567afc72577  safe App allowlist
5fc8df9d764903f7ac3d4aea18a6044123f18a00  checkpoint update
```

The first five video records showed that successful and failed sessions can have the same general structure: several P records (`NAL type 1`) before the next I record (`7,8,5`). Stable cameras can also start this way.

Conclusion: simple P-before-I ordering, I-frame size, or lack of AUD is not currently the leading explanation. Do not inject AUD without new evidence.

## FFmpeg state diagnostics — decisive evidence

Diagnostic commits:

```text
daa6ec85306676ec130656702077c840d8ccaaa5  safe FFmpeg state wrapper
dbafcdc62df3c09f7e90db9b89d701afd00e12a1  App wrapper activation/allowlist
29fa6489c7af4cf6edcdaaf564fa731685361cd0  checkpoint
```

`yi_ffmpeg_state_wrapper.py` runs only for the known YI live mux path. It raises FFmpeg loglevel from `warning` to `info`, consumes stderr internally and exposes only fixed state markers.

Latest PTZ failed startup proved all of these before the 45 s stall:

```text
ffmpeg_state=diagnostic_active
ffmpeg_state=video_input_open
ffmpeg_state=video_stream_info
ffmpeg_state=audio_input_open
ffmpeg_state=audio_stream_info
ffmpeg_state=output_mpegts_ready
ffmpeg_state=stream_mapping_ready
```

Yet no MPEG-TS byte appeared until the watchdog sent SIGTERM. Immediately during shutdown:

```text
mpegts_stdout_first_chunk_bytes=...
ffmpeg_state=stderr_eof;video_input=1;video_stream=1;audio_input=1;audio_stream=1;mapping=1;output=1
```

This is decisive: the primary startup-stall class is **after FFmpeg has opened both inputs, discovered stream information, created the MPEG-TS output and completed stream mapping, but before it emits its first output packet**.

Therefore the following are now strongly ruled out as the primary explanation for this class:

- absent P-frames
- absent SPS/PPS/IDR
- large probing windows
- failure to identify H264
- failure to identify AAC
- failure to create the MPEG-TS output
- failure to create stream mapping

The remaining leading area is FFmpeg output packet scheduling/interleave/timestamp behavior.

## PTZ has multiple independent failure classes

Do not collapse them into one bug.

### Class A — FFmpeg post-init startup stall

Pattern:

```text
TNP auth PASS
native media readers STARTED
I/P/audio records present
mpegts_mux=STARTED
all FFmpeg state milestones reached
45 s with zero TS bytes
exit 74
SIGTERM
first TS chunk appears immediately
clean worker/mux exit
```

This is the target of the current A/B experiment.

### Class B — no initial I-frame

Latest log also captured a PTZ generation with:

```text
channel1_records=28
channel2_records=0
channel3_records=37
video_frames=0
```

The reorder buffer correctly did not start the mux because no channel-2 I-frame arrived. This is a camera/session source behavior and is separate from Class A.

### Class C — native worker exit 60

PTZ also intermittently produces:

```text
native_worker_exit=60
relay_exit_rc=81
```

This occurs before normal media startup and is separate from the FFmpeg post-init stall.

### Class D — post-start native header starvation

PTZ can successfully publish more than 1 MB and later hit:

```text
code=100
qemu_alive_ffmpeg_alive_native_header_wait
```

This is a later source/session starvation state, not the startup mux problem.

## `6a046d860b2d` is also independently unstable

It has shown:

- startup exit 74
- post-start code 100 native-header wait
- code 102 audio-pipe write stall
- occasional process-group SIGTERM/SIGKILL requirement

Do not treat all `6a` failures as the same PTZ root cause.

## Current temporary A/B experiment — PTZ MPEG-TS video-only output

### Source commits

```text
8db7d48162fee17b89e4b78bc247f7004a066ad6  initial video-only mapping experiment
0fecfe106b5f06c17901e3eb4658aeb8927d3ed6  fix PTZ runtime detection by ancestor scan
```

Changed file:

```text
yi_ffmpeg_state_wrapper.py
```

### Scope

Only YI live FFmpeg invocations associated with runtime stable-id:

```text
e2f22804fecd
```

are modified.

The initial `8db7d481...` implementation looked only at FFmpeg's direct parent for `--stable-id e2f22804fecd`. HA deployment logs proved that this did **not** match the real runtime topology: every PTZ FFmpeg summary still showed `video_only=0`, and `ffmpeg_state=ptz_video_only_ab_active` never appeared. Therefore the 2026-08-26 14:46 log is **not an A/B result** and must not be interpreted as evidence for or against AAC/interleave.

`0fecfe106...` replaces direct-parent-only detection with a bounded, secret-safe Linux `/proc` ancestor scan (maximum 8 ancestors). It checks command lines only for the exact `--stable-id` pair and never logs command line contents, PIDs or other process data.

All other cameras remain normal H264+AAC live output. Non-live/finite FFmpeg invocations are passed through unchanged.

### Exact experiment behavior when activation is confirmed

For PTZ live only:

- H264 input remains unchanged;
- AAC input remains open and consumed normally, so the existing relay audio writer does not block merely because of the test;
- output mapping removes only `-map 1:a:0`;
- the AAC `-bsf:a` is removed because audio is no longer mapped;
- H264 is still stream-copied; no transcoding;
- MPEG-TS output becomes video-only;
- PPPP/TNP, native worker, two-stage 9029/768, H264 parsing, watchdog timeouts and reorder logic are unchanged.

Safe activation marker:

```text
ffmpeg_state=ptz_video_only_ab_active
```

The final stderr summary must include:

```text
video_only=1
```

for valid PTZ experiment generations. Other cameras should show `video_only=0`.

### Interpretation criteria

**If PTZ video-only starts producing TS immediately/reliably:**

Strong evidence that Class A is caused by the mapped AAC path, A/V timestamp relationship, or MPEG-TS A/V interleave/output scheduling. Next experiment should isolate which of those three is responsible while restoring audio afterward.

**If PTZ video-only still reaches the video FFmpeg milestones and then stalls until EOF:**

AAC output/interleave is not sufficient to explain Class A. Focus next on H264 packet timing/SETTS/FFmpeg mux scheduling on the video path.

**If a generation has channel2=0:**

Do not count that generation when judging the A/B result; the mux never has a decodable video start and this belongs to Class B.

**If worker exit=60 occurs:**

Also exclude that generation from Class-A A/B evaluation; it is Class C.

### Latest deployment evidence

The App rebuilt/restarted successfully at about 14:46 local time and the normal FFmpeg state wrapper was active. The PTZ continued to show Class-A stalls with complete A/V FFmpeg milestones, but all PTZ shutdown summaries explicitly showed:

```text
video_only=0
```

Examples in that run included valid Class-A generations with channel2 records present, all FFmpeg milestones reached, exit 74, and first TS only on SIGTERM. Because `video_only=0`, those generations only reconfirm the existing A/V failure and do not test the new hypothesis.

The same run also showed `6a046d860b2d` post-start code-100 native-header stalls; those remain independent.

### Current deployment state

At the time of this checkpoint update:

- FFmpeg state diagnostic wrapper is deployed and proven;
- H264 shape diagnostics are deployed and proven;
- initial A/B commit `8db7d481...` was deployed but **failed to activate** for PTZ because direct-parent detection did not match;
- corrected A/B activation commit `0fecfe106...` is in GitHub and **not yet confirmed deployed to HA**;
- no worker rebuild is required;
- `run.sh` does not need another change because `ffmpeg_state=` is already allowlisted.

## Next deployment step

Because only root-level Python `yi_ffmpeg_state_wrapper.py` changed after the failed activation:

1. laptop: pull branch, py_compile, run `tools/prepare_ha_app_context.py`, copy the staged wrapper into `/addons/yi_home/rootfs/opt/yi-home/app/`;
2. HA: rebuild and restart `local_yi_home`;
3. **first requirement:** confirm `ffmpeg_state=ptz_video_only_ab_active` appears for `camera=e2f22804fecd` and PTZ summary later reports `video_only=1`;
4. only after activation is proven, collect several valid Class-A PTZ generations;
5. compare whether they now reach `mpegts_stdout_first_chunk_bytes` promptly instead of exit 74;
6. do not judge generations with channel2=0 or worker exit=60 as evidence for/against the FFmpeg A/B hypothesis.

## Do not do next

- Do not start Phase 6E.
- Do not increase startup/stall timeouts.
- Do not add blind retries or additional 9029 commands.
- Do not inject AUD yet.
- Do not reopen solved Frigate networking/audio/export work.
