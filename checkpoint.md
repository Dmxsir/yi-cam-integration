# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-08-26_  
_Branch: `phase-3-linux-pppp`  
_Repository: `Dmxsir/yi-cam-integration`

## Purpose

This is the canonical handoff/context document for continuing the YI camera reverse-engineering / Home Assistant project in a new ChatGPT chat or after context loss.

**Repository workflow rule:** every source change must be followed by an update to this `checkpoint.md` so code state, deployment state, evidence and next step remain synchronized.

## Interaction / deployment workflow

The user wants a minimal command workflow:

1. Assistant edits the GitHub repository directly.
2. User gets **one command for the laptop**.
3. User gets **one command for Home Assistant**.
4. Do not send long command sequences. Wait for results and proceed from evidence.

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

## High-level architecture

```text
YI camera
 -> PPPP/TNP native session
 -> AArch64 native worker under QEMU
 -> H264 + AAC native records
 -> Python relay
 -> FFmpeg MPEG-TS mux
 -> App-owned go2rtc / RTSP
 -> HA OS mapped RTSP host port
 -> external Frigate
```

The App owns camera runtime lifecycle and go2rtc publication. Frigate is only a consumer.

## Completed Phase 6G — Frigate integration/export

Phase 6G is complete and should not be reopened unless a real regression appears.

Stable Frigate source format:

```text
rtsp://<HA-host>:<mapped-port>/yi_<stable-prefix>
```

Known example:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

Mapped host port is discovered through Supervisor and must not be hardcoded in code.

Frigate live audio needs an Opus branch in Frigate go2rtc, while recordings preserve source audio.

Example:

```yaml
go2rtc:
  streams:
    yi_pool:
      - rtsp://10.0.0.16:28554/yi_867ecdee5a36
      - "ffmpeg:yi_pool#audio=opus"
```

Recording:

```yaml
ffmpeg:
  output_args:
    record: preset-record-generic-audio-copy
```

Previously validated:

- live video
- audio
- detection
- recording
- stream OFF/ON lifecycle
- secret-safe Frigate export

Do **not** start Phase 6E while the runtime restart storm below remains unresolved.

## Camera runtime IDs relevant to current debugging

```text
e2f22804fecd = PTZ front camera
867ecdee5a36 = pool
6a046d860b2d = unstable camera; exact friendly-name mapping not fixed in this checkpoint
```

Do not guess other stable-ID/name mappings without explicit evidence.

## Supervisor exit/stall codes

From `yi_native_session_supervisor.py`:

```text
74  = EXIT_STARTUP_STALL
75  = generic media stall
81  = native worker failure propagated by relay wrapper
88  = relay runtime error
100 = native_header_wait
101 = native_payload_wait
102 = audio_pipe_write
103 = video_pipe_write
104 = mux_starting
105 = relay_processing
```

Interpretation:

- `74`: no MPEG-TS bytes reached the supervisor inside the 45 s startup window.
- `100`: media had already started and then the relay waited for the next native record header for 12 s.
- `102`: FFmpeg audio input writer blocked for the watchdog interval.

These codes do not automatically prove the PPPP connection itself is dead.

## Native worker exit meanings

For `android_pppp_av_stream`:

```text
40 = PPPP_Connect returned negative
50 = initial PPPP_Write failure
60 = first channel-0 PPPP_Read failed / did not return exactly 8 bytes
61/62/63 = response framing/body/auth failure
71 = media thread creation failure
72 = media reader failure
73 = second-stage refresh thread creation failure
```

Observed negative connection value:

```text
0xFFFFF445 = signed -3003
```

Its semantic meaning is not proven. Do not label it timeout/already-connected/etc.

## Official TNP two-stage live startup

Golden trace:

```text
docs/tnp-network-golden-trace.md
```

The official current client proves a two-stage live start.

Relevant commands:

```text
4881 = SET_RESOLUTION
4882 = SET_RESOLUTION response
9029 = START_REALTIME
768  = START_AUDIO
767  = STOP_LIVE
```

Official pattern:

```text
T+~3 ms     9029 no.2  use-count=1
             768 no.3

T+~5928 ms  9029 no.11 use-count=2
             768 no.12
```

The second `9029 + 768` is capture-proven, not a blind retry.

## Two-stage native worker implementation

Commit:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

The worker keeps the existing `Y3F1` host payload protocol. It derives the first-stage realtime command locally and sends the second `9029 + 768` about 5.9 s later.

No Python host protocol change was required.

Worker build/staging helper:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

File:

```text
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
```

Validated worker build/stage result:

```text
phase3g_worker_build=PASS
PHASE6D_APP_CONTEXT_PREPARE=PASS
PHASE3G_WORKER_STAGE=PASS
```

Deployed worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

The runtime logs prove the second `9029 + 768` pair is actually sent on all cameras.

## App build/staging rule

`yi_home/Dockerfile` uses:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

Therefore:

- `yi_home/run.sh` changes can be copied directly to `/addons/yi_home/run.sh` and require App rebuild.
- root Python source changes require `python3 tools/prepare_ha_app_context.py` before copying the staged file(s) into `/addons/yi_home/rootfs/...`.
- native C worker changes require compiling/staging the worker binary.

Do not assume a root-level Python edit reaches the HA App automatically.

## Graceful shutdown behavior

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

The supervisor first SIGTERMs the relay parent so the relay can request worker STOP/BREAK/FORCECLOSE and exit cleanly. Only after the grace period does it fall back to process-group SIGTERM/SIGKILL.

PTZ often exits cleanly after watchdog termination:

```text
native_worker_exit=0
mpegts_mux_exit=0
terminate_result=graceful_relay_exit
```

`6a046d860b2d` still frequently exceeds the grace period and needs group SIGTERM/SIGKILL.

## Safe App diagnostics

Recent diagnostic commits include:

```text
fdaeaf88694f62f770664e98d3476b69626bcda4  runtime supervisor diagnostics
ece12824...                                      native worker summary
06c95a5...                                       PPPP startup diagnostics
80f3dc88b0484c98e5859196271f909940231c87  startup-stall relay stage
51de1808d318ae6e6f34f47cf9936aef44b40513  safe MPEG-TS startup diagnostics
ccb2d0b1d2db401105fd1635334dacce157c6415  native channel record counters
```

`yi_home/run.sh` exposes only fixed safe prefixes. Current useful values include:

```text
PPPP_Initialize_rc_hex=
PPPP_Connect_rc_hex=
PPPP_Write_4881_rc_hex=
PPPP_Write_9029_rc_hex=
PPPP_Write_768_rc_hex=
tnp_response_version=
tnp_response_command=
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
native_worker_exit=
```

Never expose arbitrary relay/worker stderr or credentials.

## Channel meaning now established for diagnostics

The native channels used by the current relay are:

```text
channel1 = AAC audio records
channel2 = I-frame video records
channel3 = P-frame video records
```

The Python decoder runs H264 NAL analysis through `yi_live_relay._decode_video_unit()` / `oracle.analyze_nals()` and stores the resulting safe integer list in `nal_unit_types`.

## PTZ startup problem — evidence before minimal probing

The PTZ repeatedly showed this pattern:

```text
TNP auth PASS
media readers STARTED
initial_av_delta_ms ~= tens of milliseconds
mpegts_mux=STARTED
45 s without TS bytes
startup_stall code=74
SIGTERM relay parent
mpegts_stdout_first_chunk_bytes appears only during shutdown
worker/mux exit 0
```

Native channel counters proved normal video records were arriving even on failed startups. Examples included:

```text
channel1=30, channel2=1, channel3=35
channel1=19, channel2=1, channel3=23
channel1=36, channel2=1, channel3=27
```

Therefore the failure is not simply “no P-frames”.

## Minimal FFmpeg probing experiment

Commit:

```text
328fd031caaee8a13b4b74bc2234f57cb9895874
```

Live-only FFmpeg options were changed from the earlier bounded probe windows to:

```text
video probesize      = 4096
video analyzeduration = 0
video fpsprobesize    = 0
audio probesize       = 1024
audio analyzeduration = 0
```

Finite file validation path remained unchanged.

Deployment was verified directly on HA by grepping the staged App source and seeing:

```text
mpegts_streaming_probe_tuning=video_probe_4096/video_analyze_0/video_fpsprobe_0/audio_probe_1024/audio_analyze_0/...
```

### Result

Minimal probing **did not eliminate PTZ startup stalls**.

Fresh post-deployment log repeatedly showed:

```text
mpegts_mux=STARTED
startup_stall code=74 after 45 s
channel2 > 0
channel3 > 0
first MPEG-TS chunk appears only after watchdog SIGTERM
```

Concrete post-change examples:

```text
channel1=53, channel2=1, channel3=59
channel1=32, channel2=1, channel3=34
channel1=57, channel2=2, channel3=56
channel1=40, channel2=1, channel3=51
channel1=56, channel2=1, channel3=71
channel1=28, channel2=1, channel3=30
channel1=90, channel2=3, channel3=104
```

The same build also sometimes succeeds immediately, proving the code/FFmpeg combination can start correctly on some generations:

```text
mpegts_mux=STARTED
mpegts_stdout_first_chunk_bytes=940
media_started=true
```

This makes a deterministic “probesize too large” explanation unlikely.

## Current PTZ startup hypothesis

The strongest next hypothesis is **first-I-frame H264 structure**, not P-frame count.

The relay may receive an I-frame record that differs between generations in whether it contains the parameter-set / random-access NAL units FFmpeg needs at stream start.

Important H264 NAL types:

```text
5 = IDR slice
7 = SPS
8 = PPS
```

If a failing generation receives I/P records but its first emitted I-frame lacks SPS/PPS and/or IDR, FFmpeg may keep waiting for enough codec initialization information even though record counters continue increasing.

If failed and successful generations show the same SPS/PPS/IDR set, this hypothesis is disproved and debugging must move deeper into FFmpeg/parser/timestamps/pipe behavior.

## New NAL startup diagnostic — current source head

Commit:

```text
b3fa9d06c9e976447f5f3570d3915f14331c953d
```

Message:

```text
Expose first H264 NAL startup diagnostics
```

Changed:

```text
yi_native_av_relay.py
```

Behavior change: **diagnostics only**. No TNP, timeout, retry, worker, FFmpeg option or watchdog behavior was changed.

The relay records the NAL type list of the first video frame emitted by the reorder buffer and appends a secret-safe summary to the existing allowlisted `mpegts_mux=STARTED` line.

Expected log format:

```text
mpegts_mux=STARTED; first_video_nal_types=7,8,5; first_video_has_sps=1; first_video_has_pps=1; first_video_has_idr=1
```

The existing `run.sh` already allowlists lines beginning with:

```text
[phase3g-relay] mpegts_mux=STARTED
```

so **no `run.sh` modification is required** for this diagnostic.

### What to compare after deployment

Collect enough App log to include:

1. at least one PTZ generation that ends in `startup_stall code=74`;
2. ideally one PTZ generation that reaches `media_started=true`;
3. a stable camera startup for comparison.

For each generation compare:

```text
first_video_nal_types=
first_video_has_sps=
first_video_has_pps=
first_video_has_idr=
```

Interpretation:

- Failed PTZ lacks SPS/PPS/IDR while successful/stable generation has them -> strong root-cause evidence in first-I-frame structure.
- Failed and successful PTZ both have SPS/PPS/IDR -> H264 initialization NAL hypothesis is not enough; investigate FFmpeg parser/timestamp/pipe behavior next.
- `first_video_nal_types=none` -> decoder metadata propagation needs checking before drawing conclusions.

## PTZ post-start stall is a separate failure mode

Even when PTZ successfully publishes TS, it can later hit:

```text
media_stall_detected
stall_process_state=qemu_alive_ffmpeg_alive_native_header_wait
code=100
```

Examples from the latest full log show PTZ had already forwarded roughly 1.3-1.8 MB and accumulated hundreds of records before the native header wait.

This means the startup-mux issue and later source-record starvation must be treated separately.

Do not assume fixing first-I-frame startup will automatically fix code 100.

## `6a046d860b2d` remains a separate unstable runtime

It can start and publish MPEG-TS, but later exhibits multiple failure states:

```text
code 100 = native_header_wait
code 102 = audio_pipe_write
code 105 = relay_processing
```

Latest log examples include multi-megabyte successful publication before failure, e.g. around 9 MB before an `audio_pipe_write` watchdog event with thousands of audio records and hundreds of video records.

Its shutdown often requires process-group SIGTERM then SIGKILL.

Do not merge this failure mode with the PTZ startup code-74 problem without evidence.

## Current deployment status

At the moment this checkpoint was updated:

- minimal-probing commit `328fd031...` **is deployed and verified** in HA;
- safe channel counter commit `ccb2d0b...` **is deployed**;
- two-stage worker is deployed;
- new NAL diagnostic commit `b3fa9d06...` **is in GitHub but has not yet been confirmed deployed to HA**.

The next deployment should therefore stage/copy only the updated Python App source and rebuild/restart the App. Native worker rebuild is not required.

## Next deployment workflow

Laptop command should perform, in one command:

```text
git pull -> prepare_ha_app_context.py -> copy staged yi_native_av_relay.py to HA App rootfs
```

HA command should perform, in one command:

```text
ha apps rebuild local_yi_home && ha apps restart local_yi_home
```

After restart, allow the runtime to run without manual restarts and capture the App log after PTZ has produced at least one failure/success cycle.

## Do not do yet

Without new evidence:

- do not increase startup timeout
- do not increase stall timeout
- do not add blind retries
- do not add extra 9029 commands beyond the capture-proven two-stage sequence
- do not change TNP use-count again
- do not change native worker for the NAL diagnostic
- do not start Phase 6E
- do not reopen solved Frigate networking/audio/export work
- do not interpret worker SIGTERM (`-15`) as a camera protocol error
- do not assign a semantic label to PPPP `-3003`
- do not expose credentials, DIDs, device keys, tokens, raw auth payloads or raw H264/AAC content

## Secret-safety rules

Diagnostics must remain fixed-format and secret-safe.

Allowed categories include:

- PPPP return codes
- TNP command/version/auth result
- PASS markers
- stable camera ID prefix
- supervisor state / exit code
- record/frame counts
- A/V timing offsets
- MPEG-TS byte counts
- fixed H264 NAL type integers/booleans

Do not mirror arbitrary stderr to App stdout.

## Key files

```text
tools/phase3_pppp_probe/android_pppp_av_stream.c
tools/phase3_pppp_probe/run_phase3e_tnp.py
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
tools/prepare_ha_app_context.py
yi_live_relay.py
yi_native_av_relay.py
yi_native_av_relay_stable.py
yi_native_session_supervisor.py
yi_runtime_lifecycle.py
yi_home/run.sh
docs/tnp-network-golden-trace.md
checkpoint.md
```

## Important recent commits

```text
1a561997cdb9e9ef3561f657ae32a5c5aed28d60  Mark Phase 6G Frigate integration complete
c97e5555bdd26ffd72c7df1583d8512ccbef5c15  Gracefully stop relay before process-group fallback
80f3dc88b0484c98e5859196271f909940231c87  Expose relay stage on startup stalls
51de1808d318ae6e6f34f47cf9936aef44b40513  Expose safe MPEG-TS startup diagnostics
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151  Mirror official two-stage TNP live startup
7c1e6cee8fa517cf4931a951e39200f8fffffb7e  Add one-step Phase 3G worker staging helper
ccb2d0b1d2db401105fd1635334dacce157c6415  Expose safe native channel record counters
328fd031caaee8a13b4b74bc2234f57cb9895874  Minimal live FFmpeg probing experiment
b3fa9d06c9e976447f5f3570d3915f14331c953d  Expose first H264 NAL startup diagnostics
```

## Immediate next step

Deploy `b3fa9d06...`, then inspect `mpegts_mux=STARTED` lines for the first-frame SPS/PPS/IDR summary and correlate them with `startup_stall` vs `media_started`.
