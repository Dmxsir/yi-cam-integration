# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-08-26_  
_Branch: `phase-3-linux-pppp`_  
_Repository: `Dmxsir/yi-cam-integration`_

## Purpose

This is the canonical handoff/context document for continuing the project in a new ChatGPT chat or after context loss.

**Mandatory workflow rule:** every repository change must also update this `checkpoint.md` with the current code state, runtime evidence, deployment status, constraints, and next step.

## Interaction / deployment workflow

The user explicitly wants a minimal operational workflow:

1. Assistant changes the GitHub repository directly.
2. Give the user **one command for the laptop**.
3. Give the user **one command for Home Assistant**.
4. Do not dump large command sequences; wait for the result and continue.

Canonical laptop checkout:

```text
~/Documents/yi-cam-integration-phase3
```

Canonical branch:

```text
phase-3-linux-pppp
```

Home Assistant OS host:

```text
10.0.0.16
```

HA integration path:

```text
/config/custom_components/yi_home
```

Local App path:

```text
/addons/yi_home
```

App slug:

```text
local_yi_home
```

Public names:

- App: **YI RTSP**
- Integration: **YI Camera Connect**

Internal identifiers remain `yi_home`.

## Overall project status

The project reverse-engineers YI Home camera connectivity so the cameras can be consumed by Home Assistant / Frigate without the phone being part of the live media path.

Current architecture:

```text
YI camera
  -> PPPP/TNP native session
  -> native H264 + AAC relay
  -> FFmpeg MPEG-TS mux
  -> App-owned go2rtc / RTSP
  -> HA OS mapped RTSP port
  -> external Frigate
```

The App owns camera runtime and publication. Frigate is only a consumer.

## Completed: Phase 6G Frigate integration/export

Phase 6G is complete and should not be reopened unless new regression evidence appears.

Stable source pattern:

```text
rtsp://<HA-host>:<mapped-port>/yi_<stable-prefix>
```

Example PTZ source:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

Mapped RTSP host port is dynamically discovered through Supervisor and must not be hardcoded in code.

Frigate live audio uses an Opus branch in Frigate go2rtc while recordings preserve source audio, e.g.:

```yaml
go2rtc:
  streams:
    yi_pool:
      - rtsp://10.0.0.16:28554/yi_867ecdee5a36
      - "ffmpeg:yi_pool#audio=opus"
```

Recording pattern:

```yaml
ffmpeg:
  output_args:
    record: preset-record-generic-audio-copy
```

Previously validated:

- live video
- audio
- Frigate detection
- Frigate recording
- stream OFF/ON lifecycle
- secret-safe export/inventory

## Current blocker: restart storm

Do **not** start Phase 6E until runtime instability is resolved.

Problematic IDs currently observed:

```text
e2f22804fecd = PTZ front
6a046d860b2d = name not explicitly mapped in this checkpoint
```

Known mapping:

```text
867ecdee5a36 = pool
```

Do not guess other camera-name mappings.

## Supervisor exit codes currently relevant

From `yi_native_session_supervisor.py`:

```text
74  = EXIT_STARTUP_STALL
75  = generic media stall
81  = native worker failure propagated by relay wrapper
88  = relay runtime error
100 = native_header_wait media stall
101 = native_payload_wait
102 = audio_pipe_write
103 = video_pipe_write
104 = mux_starting
105 = relay_processing
```

Interpretation:

- `74`: no MPEG-TS bytes reached the supervisor within the 45 s startup timeout.
- `100`: media had started previously; relay is now waiting for the next native record header.
- `102`: live audio writer to FFmpeg is blocked.

These codes do not automatically mean PPPP is disconnected.

## Native worker exits

For `android_pppp_av_stream`:

```text
40 = PPPP_Connect returned negative
50 = one or more PPPP_Write calls failed
60 = first channel-0 PPPP_Read failed / non-8-byte header
61/62/63 = later response framing/body/auth validation failures
```

Observed connect value:

```text
0xFFFFF445 = signed -3003
```

Its semantic meaning is **not proven**. Do not label it timeout/already-connected/etc.

## Official TNP golden trace

Canonical document:

```text
docs/tnp-golden-trace.md
```

Current official 6.9.7 capture proves a two-stage realtime start for the modern client.

Important commands:

```text
9029 = START_REALTIME
768  = AUDIOSTART
767  = STOP
4881 = SET_RESOLUTION
4882 = SET_RESOLUTION response
```

Official current-client timing:

```text
T+0 ms       9031 no.1
T+3 ms       9029 no.2  use-count=1
              768 no.3
              ...
T+5928 ms    9029 no.11 use-count=2
              768 no.12
```

The second `9029 + 768` is runtime-proven, not a guessed retry.

The first subscription produces an initial channel-2 I-frame with use-count 1. Continuous channel-1/channel-3 traffic begins around the second `9029` with use-count 2.

## Two-stage worker change

Commit:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

Message:

```text
Match official two-stage realtime startup
```

Behavior:

1. Host payload format remains the original four-unit `Y3F1` format.
2. Worker derives the official first 9029 with use-count 1.
3. Original use-count-2 9029 becomes second-stage command.
4. About 5.9 s later worker sends second `9029 + 768` with official command numbers 11/12.

The host Python protocol was deliberately not changed.

## Worker build/staging helper

Commit:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

Helper:

```text
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
```

Previously validated output:

```text
phase3g_worker_build=PASS
PHASE6D_APP_CONTEXT_PREPARE=PASS
PHASE3G_WORKER_STAGE=PASS
```

Staged worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

That worker is already deployed in the HA App.

## App staging rules — important

`yi_home/Dockerfile`:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

`tools/prepare_ha_app_context.py` copies root-level Python files to:

```text
yi_home/rootfs/opt/yi-home/app/
```

and the native/Bionic runtime to:

```text
yi_home/rootfs/opt/yi-home/runtime/bionic-root/
```

Therefore:

- `yi_home/run.sh` edits can be copied directly then App rebuilt.
- root Python edits must be restaged with `tools/prepare_ha_app_context.py` before HA rebuild.
- C worker edits require compile + staging.
- never assume a root source change automatically reaches the App.

## Graceful shutdown behavior

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

Supervisor sends SIGTERM to relay parent first. Relay then sends its stop byte to native worker so STOP_LIVE / PPPP cleanup can occur before process-group fallback.

PTZ often exits cleanly after watchdog shutdown:

```text
native_worker_exit=0
mpegts_mux_exit=0
terminate_result=graceful_relay_exit
```

`6a046d860b2d` can still exceed the grace period and require process-group SIGTERM/SIGKILL.

Do not increase grace blindly.

## Safe diagnostic bridge

`yi_home/run.sh` mirrors only strict fixed-prefix, secret-safe lines from private per-camera runtime logs.

Relevant commits:

```text
fdaeaf88694f62f770664e98d3476b69626bcda4  Expose safe runtime supervisor diagnostics in App logs
ece12824b3411e16459598eeca06a4c19add392c  Expose native worker summary in App diagnostics
06c95a5e2c0ebe49100e4546bcb4b0d629dffaf5  Expose safe PPPP startup diagnostics
80f3dc88b0484c98e5859196271f909940231c87  Expose relay stage on startup stalls
51de1808d318ae6e6f34f47cf9936aef44b40513  Expose safe MPEG-TS startup diagnostics
ccb2d0b1d2db401105fd1635334dacce157c6415  Expose safe native channel record counters
```

Current safe diagnostics include:

```text
PPPP_Initialize_rc_hex=
PPPP_Connect_rc_hex=
PPPP_Write_4881_rc_hex=
PPPP_Write_9029_rc_hex=
PPPP_Write_768_rc_hex=
tnp_response_version=
tnp_response_command=
tnp_response_command_number=
tnp_auth_result=
phase3g_tnp_auth=PASS
phase3g_media_readers=STARTED
channel1_records=
channel2_records=
channel3_records=
initial_av_delta_ms=
mpegts_mux=STARTED
mpegts_stdout_first_chunk_bytes=
mpegts_stdout_pumped_bytes=
```

Never mirror arbitrary stderr, command lines, UID/DID, device keys, auth payloads, passwords, account tokens, or API tokens.

## Decisive channel-counter evidence — 2026-08-26

The counter instrumentation resolved the earlier uncertainty about whether PTZ was missing P-frames.

### PTZ startup stall examples

For `e2f22804fecd`, one exit-74 generation showed:

```text
channel1_records=30
channel2_records=1
channel3_records=35
video_frames=36
audio_frames=30
```

Yet the first MPEG-TS chunk appeared only after supervisor SIGTERM began.

Another generation showed:

```text
channel1_records=19
channel2_records=1
channel3_records=23
video_frames=24
audio_frames=19
```

Again, no supervisor-visible TS until shutdown.

Another showed:

```text
channel1_records=36
channel2_records=1
channel3_records=27
video_frames=26
audio_frames=36
```

Again, the first TS chunk appeared only when the relay was being terminated.

### Meaning

This decisively rules out the previous hypothesis that PTZ startup stalls happen because continuous P-frames are absent.

During failed startup generations the host has:

- audio packets
- an I-frame
- many P-frames
- valid A/V timestamps
- an FFmpeg mux process that is alive

but FFmpeg often does not emit MPEG-TS until the input is closed.

The primary PTZ startup suspect is therefore **FFmpeg raw H264/AAC stream-info probing/buffering**, not missing PPPP/TNP media subscription.

### `6a046d860b2d` startup evidence

One startup-stall generation showed:

```text
channel1_records=195
channel2_records=4
channel3_records=13
```

and the first MPEG-TS bytes also appeared only during termination.

So the same FFmpeg startup buffering behavior is not unique to PTZ.

## Separate post-start source stalls still exist

The FFmpeg startup issue is not the only failure mode.

### PTZ post-start native-header stall

A later PTZ generation successfully emitted media, then after ~1.17 MB stopped producing new native records:

```text
media_stall_detected=true
forwarded_bytes=1170864
stall_process_state=qemu_alive_ffmpeg_alive_native_header_wait
code=100
```

At shutdown the worker counters were substantial:

```text
channel1_records=237
channel2_records=5
channel3_records=284
```

This is a separate problem: media had already started successfully, then the native source stopped advancing.

### `6a046d860b2d` post-start stalls

Observed both:

```text
code=100 native_header_wait
```

and:

```text
code=102 audio_pipe_write
```

One code-102 example had already forwarded more than 10 MB and accumulated:

```text
channel1_records=2841
channel2_records=84
channel3_records=853
```

So `6a046...` has a distinct long-running stability problem in addition to the startup-probe problem.

Do not conflate the two failure classes.

## Latest code change: minimal Live FFmpeg probing

Commit:

```text
328fd031caaee8a13b4b74bc2234f57cb9895874
```

Message:

```text
Minimize live FFmpeg input probing
```

Changed file:

```text
yi_native_av_relay.py
```

Scope is intentionally limited to `_start_ffmpeg_stdout()` — the live stdout/go2rtc path only.

Previous Live H264 input tuning:

```text
-probesize 262144
-analyzeduration 500000
-r 20
-f h264
```

Previous Live AAC input tuning:

```text
-probesize 32768
-analyzeduration 200000
-f aac
```

New Live H264 tuning:

```text
-probesize 4096
-analyzeduration 0
-fpsprobesize 0
-r 20
-f h264
```

New Live AAC tuning:

```text
-probesize 1024
-analyzeduration 0
-f aac
```

The existing settings remain:

```text
-thread_queue_size 512
-fflags +nobuffer          # video input
-flush_packets 1
-muxdelay 0
-muxpreload 0
-mpegts_flags +resend_headers
```

The stable wrapper still supplies:

```text
-max_interleave_delta 500000
```

No change was made to:

- PPPP
- TNP command sequence
- the two-stage 9029 behavior
- worker binary
- startup timeout (45 s)
- media stall timeout (12 s)
- retries
- finite `--output` validation/file path

New safe relay log string for the live path:

```text
mpegts_streaming_probe_tuning=video_probe_4096/video_analyze_0/video_fpsprobe_0/audio_probe_1024/audio_analyze_0/thread_queue_512/flush_packets
```

### Hypothesis being tested

Because the formats are already explicitly declared as raw H264 and AAC and the input frame rate is already known (`-r 20`), large stream-info windows are unnecessary for the live path.

Expected success pattern after deployment:

```text
initial_av_delta_ms=...
mpegts_mux=STARTED
mpegts_stdout_first_chunk_bytes=...
media_started=true
```

with `mpegts_stdout_first_chunk_bytes` appearing promptly, not only after watchdog SIGTERM.

If this significantly reduces PTZ exit-74 restarts, the FFmpeg startup-probing hypothesis is validated.

If exit 74 remains and the first chunk still appears only during shutdown, next investigation should focus on FFmpeg mux/interleave/packet timestamp behavior rather than TNP.

## Deployment status of latest commit

At the time of this checkpoint update:

- `328fd031...` is committed to GitHub.
- `checkpoint.md` is updated for the new test.
- The user has **not yet confirmed pulling/staging/deploying `328fd031...` to HA**.

Required deployment model for this Python-only change:

1. Laptop: pull branch, run `tools/prepare_ha_app_context.py`, then copy the staged `yi_native_av_relay.py` into the HA App rootfs.
2. HA: rebuild and restart `local_yi_home`.

Because the user wants one laptop command and one HA command, combine each environment's operations into one shell command.

## What to inspect after deployment

Let all five cameras run for several minutes without manual restarts.

Primary test targets:

```text
e2f22804fecd
6a046d860b2d
```

For PTZ, compare restart rate and look for:

```text
mpegts_mux=STARTED
mpegts_stdout_first_chunk_bytes=...
media_started=true
```

If `media_started=true` appears quickly and exit-74 loops largely disappear, do not immediately change anything else; observe long enough to isolate remaining code-100 source stalls.

For `6a046...`, separately track:

```text
code=100 native_header_wait
code=102 audio_pipe_write
```

The minimal-probe change is expected to address startup buffering only, not necessarily post-start source/writer stalls.

## Constraints / do not do without new evidence

- Do not increase startup timeout.
- Do not increase media-stall timeout as a workaround.
- Do not add blind retries.
- Do not add more 9029 commands beyond the official two-stage sequence.
- Do not start Phase 6E yet.
- Do not reopen solved Frigate networking/audio/export issues.
- Do not interpret `-3003` beyond a negative PPPP connect result.
- Do not treat watchdog SIGTERM (`-15`) as a camera protocol error.
- Do not modify C worker unless evidence requires it; C changes require binary rebuild/staging.
- Do not use raw private GitHub curl commands on HA.
- Do not guess camera-name mapping.
- Do not expose secrets/raw worker stderr.

## Key files

```text
checkpoint.md
docs/tnp-golden-trace.md
tools/phase3_pppp_probe/android_pppp_av_stream.c
tools/phase3_pppp_probe/run_phase3e_tnp.py
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
tools/prepare_ha_app_context.py
yi_native_av_relay.py
yi_native_av_relay_stable.py
yi_native_session_supervisor.py
yi_runtime_lifecycle.py
yi_home/run.sh
```

## Important recent commits

```text
1a561997cdb9e9ef3561f657ae32a5c5aed28d60  Mark Phase 6G Frigate integration complete
fdaeaf88694f62f770664e98d3476b69626bcda4  Expose safe runtime supervisor diagnostics in App logs
ece12824b3411e16459598eeca06a4c19add392c  Expose native worker summary in App diagnostics
06c95a5e2c0ebe49100e4546bcb4b0d629dffaf5  Expose safe PPPP startup diagnostics
c97e5555bdd26ffd72c7df1583d8512ccbef5c15  Gracefully stop relay before process-group fallback
80f3dc88b0484c98e5859196271f909940231c87  Expose relay stage on startup stalls
51de1808d318ae6e6f34f47cf9936aef44b40513  Expose safe MPEG-TS startup diagnostics
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151  Match official two-stage realtime startup
7c1e6cee8fa517cf4931a951e39200f8fffffb7e  Add Phase3G worker build/staging helper
ccb2d0b1d2db401105fd1635334dacce157c6415  Expose safe native channel record counters
4541006411fa6d03503f710a48f2c54d985b5560  Create canonical checkpoint
328fd031caaee8a13b4b74bc2234f57cb9895874  Minimize live FFmpeg input probing
```

## Immediate next step

Deploy `328fd031...` using exactly one laptop command and one HA command, then collect a fresh App log after several minutes.

The next decision must be based on whether PTZ exit-74 startup loops disappear or substantially decrease under minimal Live probing.
