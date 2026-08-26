# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-08-26_  
_Branch: `phase-3-linux-pppp`_  
_Repository: `Dmxsir/yi-cam-integration`_

## Purpose of this file

This file is the canonical handoff/context document for continuing the project in a new ChatGPT chat or after context loss.

**Workflow rule going forward:** every repository change must also update this `checkpoint.md` so the current state, evidence, deployment status, and next step remain synchronized with the code.

## Interaction / deployment workflow

The user wants a minimal command workflow:

1. Assistant changes the GitHub repository directly.
2. User receives **one command to run on the laptop**.
3. User receives **one command to run on Home Assistant**.
4. Do not dump long command sequences; proceed based on the result.

Canonical local checkout:

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

Integration path:

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

Public product names:

- App: **YI RTSP**
- Integration: **YI Camera Connect**

Internal identifiers remain `yi_home`.

## High-level project status

The project reverse-engineers YI Home camera connectivity so cameras can be used from Home Assistant / Frigate without the phone being part of the live media path.

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

The App owns the camera runtime and go2rtc publication. Frigate is only a consumer.

## Completed phase: 6G Frigate integration/export

Phase 6G is complete.

Stable Frigate source format:

```text
rtsp://<HA-host>:<mapped-port>/yi_<stable-prefix>
```

Example PTZ source:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

The mapped RTSP host port is discovered through Supervisor and must not be hardcoded in code.

Frigate live audio requires an Opus branch in Frigate go2rtc while recordings preserve source audio.

Example pattern:

```yaml
go2rtc:
  streams:
    yi_pool:
      - rtsp://10.0.0.16:28554/yi_867ecdee5a36
      - "ffmpeg:yi_pool#audio=opus"
```

Recording uses:

```yaml
ffmpeg:
  output_args:
    record: preset-record-generic-audio-copy
```

Validated previously:

- live video works
- audio works
- Frigate detection works
- Frigate recording works
- stream OFF/ON lifecycle works
- secret-safe inventory/export passes

Do **not** reopen solved Frigate networking/audio/export issues unless new regression evidence appears.

## Current blocker: runtime restart storm

Do not start Phase 6E until this instability is resolved.

Two problematic runtime IDs are currently known:

```text
e2f22804fecd  = PTZ front camera
6a046d860b2d  = camera identity not yet explicitly mapped in this checkpoint
```

Known stable IDs/names:

```text
867ecdee5a36 = pool
```

Do not guess the names of other stable IDs without explicit evidence.

## Relevant supervisor exit codes

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

Important interpretation rule:

- code 74 means no MPEG-TS bytes reached the supervisor within startup timeout
- code 100 means media previously started and then the relay is waiting for the next native record header
- these codes do not by themselves prove the camera connection is dead

## Native worker exit meanings

For `android_pppp_av_stream`:

```text
40 = PPPP_Connect returned negative
50 = one or more PPPP_Write calls failed
60 = first channel-0 PPPP_Read failed or returned a non-8-byte header
61/62/63 = later response framing/body/auth validation failures
```

Observed negative connect result:

```text
0xFFFFF445 = signed -3003
```

The semantic meaning of `-3003` is **not proven**. Do not label it timeout/already-connected/etc.

## Golden official TNP startup trace

Golden trace document:

```text
docs/tnp-golden-trace.md
```

Current official 6.9.7 capture (POOL, model83/y291ga, TNP v2) proves the modern client performs a two-stage realtime start.

Important commands:

```text
9029 = START_REALTIME
768  = AUDIOSTART
767  = STOP
4881 = SET_RESOLUTION
4882 = SET_RESOLUTION response
```

Official current-client sequence contains:

```text
T+0 ms       9031 no.1
T+3 ms       9029 no.2  payload use-count=1
              768 no.3
              ...
T+5928 ms    9029 no.11 payload use-count=2
              768 no.12
```

The second `9029 + 768` is therefore runtime-proven and is not a guessed retry.

The capture shows one initial channel-2 I-frame associated with use-count 1; continuous channel-1/channel-3 traffic begins shortly after the second `9029` with use-count 2.

## Two-stage worker change — deployed experiment

Commit:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

Message:

```text
Match official two-stage realtime startup
```

The native worker was changed so the existing host payload protocol did not need to change.

Behavior:

1. Host still supplies the existing 4881/9029/768/STOP units.
2. Worker derives the official first-stage 9029 with use-count 1.
3. Worker uses the original use-count-2 9029 as the second-stage command.
4. Roughly 5.9 seconds later the worker sends the official second-stage `9029 + 768`.

This keeps the PoC/host protocol stable and limits the change to the continuous native worker.

## Worker build/staging helper

Commit:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

Added:

```text
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
```

The user successfully ran:

```text
phase3g_worker_build=PASS
PHASE6D_APP_CONTEXT_PREPARE=PASS
PHASE3G_WORKER_STAGE=PASS
```

Built/staged worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

The new worker was then copied into the HA App rootfs and the App was rebuilt/restarted.

## Important App staging behavior

`yi_home/Dockerfile` uses:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

Therefore:

- editing `yi_home/run.sh` directly affects the rebuilt App
- root-level Python changes require the staged copies under `yi_home/rootfs/...`
- C worker changes require rebuilding and staging the compiled AArch64 worker

Do not assume a root-level source edit reaches the App automatically.

The helper script above now exists specifically to avoid stale worker staging.

## Graceful relay shutdown fix

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

The supervisor now sends SIGTERM to the relay parent first, allowing the relay to send the stop byte to the native worker and execute normal PPPP cleanup before falling back to process-group SIGTERM/SIGKILL.

This is validated in logs for PTZ: native worker and MPEG-TS mux can exit `0` and the supervisor reports `graceful_relay_exit`.

For `6a046d860b2d`, graceful shutdown still sometimes exceeds the 3-second grace and falls back to process-group termination.

Do not increase the grace period blindly without evidence.

## Safe diagnostics added so far

### Supervisor startup-stall stage

Commit:

```text
80f3dc88b0484c98e5859196271f909940231c87
```

Startup stall diagnostics now include allowlisted relay stage:

```text
startup_stall_detected=true; ... relay_stage=<safe-stage>; stall_state_source=...
```

### Safe MPEG-TS startup diagnostics

Commit:

```text
51de180
```

`yi_home/run.sh` now exposes allowlisted lines:

```text
initial_av_delta_ms=
mpegts_mux=STARTED
mpegts_stdout_first_chunk_bytes=
mpegts_stdout_pumped_bytes=
```

### Native channel-record counters

Latest source commit before this checkpoint:

```text
ccb2d0b1d2db401105fd1635334dacce157c6415
```

Message:

```text
Expose safe native channel record counters
```

`yi_home/run.sh` allowlist now also includes:

```text
channel1_records=
channel2_records=
channel3_records=
```

These counters already exist in the worker and are emitted during worker shutdown. This commit changes only log visibility, not runtime behavior.

## Latest runtime evidence after two-stage 9029 change

A fresh App log after deploying the worker proved the second `9029 + 768` is actually being sent for all cameras.

Examples in the log show the initial writes followed later by another:

```text
PPPP_Write_9029_rc_hex=0x00000034
PPPP_Write_768_rc_hex=0x00000038
```

### PTZ (`e2f22804fecd`)

The two-stage TNP change improved the early startup path:

- PPPP initialize/connect succeeds
- 4881/9029/768 writes succeed
- TNP response 4882/auth passes
- media readers start
- both video and audio frames are present
- `initial_av_delta_ms` is reasonable (examples ~28–79 ms)
- `mpegts_mux=STARTED`

However the PTZ still frequently hits startup exit 74.

Key repeated pattern:

```text
mpegts_mux=STARTED
... 45 seconds with no supervisor-visible TS ...
startup_stall_detected=true; relay_stage=native_header_read; code=74
SIGTERM relay parent
mpegts_stdout_first_chunk_bytes=...
mpegts_stdout_pumped_bytes=...
native_worker_exit=0; mpegts_mux_exit=0; video_frames>0; audio_frames>0
graceful_relay_exit
```

Concrete examples from the latest log included:

```text
video_frames=65; audio_frames=53
video_frames=24; audio_frames=26
video_frames=27; audio_frames=22
video_frames=35; audio_frames=26
video_frames=40; audio_frames=46
video_frames=25; audio_frames=49
```

This is decisive evidence that:

- camera PPPP/TNP connection is alive
- native H264 and AAC have reached the relay
- FFmpeg mux process exists
- MPEG-TS often appears only when the relay begins shutdown / pipe close

Therefore the current PTZ suspect is **FFmpeg H264 probing/buffering / stream structure**, not a missing PPPP connection.

Do not add more blind 9029 commands or increase startup timeout.

### `6a046d860b2d`

This camera also benefits from two-stage startup and can successfully reach:

```text
mpegts_stdout_first_chunk...
media_started=true
```

But it still suffers post-start media stalls.

Observed examples:

```text
code=102
stall state = qemu_alive_ffmpeg_alive_audio_pipe_write
forwarded_bytes ~= 2.7 MB
```

and:

```text
code=100
stall state = qemu_alive_ffmpeg_alive_native_header_wait
forwarded_bytes ~= 4.2 MB
```

and later another code 100 after ~1.1 MB.

Its graceful relay shutdown also sometimes hangs and requires SIGTERM/SIGKILL fallback.

Treat this as a distinct failure mode from the PTZ startup-mux behavior.

## Current diagnostic hypothesis / next test

The next diagnostic goal is to distinguish whether PTZ gives FFmpeg:

1. mostly I-frames and few/no P-frames, or
2. normal channel-2 + channel-3 video but FFmpeg still buffers output.

The worker already reports on shutdown:

```text
channel1_records = audio
channel2_records = video I-frame channel
channel3_records = video P-frame channel
```

The latest `run.sh` commit (`ccb2d0b`) exposes these values safely.

### Deployment status at the moment this checkpoint was written

The user already:

- pulled `ccb2d0b`
- copied updated `yi_home/run.sh` to:

```text
/addons/yi_home/run.sh
```

The HA rebuild/restart command was provided, but **execution confirmation had not yet been received when this checkpoint was created**.

Therefore in the next chat/session, first establish whether the App has already been rebuilt/restarted after `ccb2d0b`.

If it has, collect a fresh log until at least one PTZ exit-74 shutdown occurs and inspect:

```text
channel1_records=
channel2_records=
channel3_records=
```

Interpretation:

- `channel2 > 0` and `channel3 ~= 0`: strong evidence continuous P-frame stream is not arriving; investigate TNP subscription/use-count/stream-channel behavior further.
- `channel2 > 0` and `channel3 > 0` with substantial counts: video structure reaches host; focus on FFmpeg H264 parser/probe/buffering behavior.
- counters unavailable: verify current run.sh is actually deployed and App rebuilt.

## Current code directions / constraints

Do not do the following without new evidence:

- do not increase startup timeout
- do not add blind retries
- do not add extra 9029 commands beyond the official two-stage sequence
- do not start Phase 6E
- do not reopen solved Frigate networking/audio/export work
- do not interpret PPPP `-3003` beyond a negative connect result
- do not treat watchdog SIGTERM (`-15`) as a camera protocol error
- do not modify C worker unless required by evidence, because it requires binary rebuild/staging
- do not use raw private GitHub curl commands on HA
- do not guess camera-name mapping from stable IDs
- do not expose raw worker stderr, credentials, UID/DID, device keys, tokens, passwords, or authentication payloads

## Secret-safety rules

Diagnostics surfaced by `yi_home/run.sh` must remain strict fixed-prefix allowlists.

Safe categories currently include:

- PPPP return codes
- TNP response version/command/number/auth result
- known PASS markers
- supervisor state classifications
- safe relay stage names
- frame/record counts
- MPEG-TS byte counts
- A/V timing offsets

Never mirror arbitrary worker/relay stderr to App stdout.

## Key files

```text
tools/phase3_pppp_probe/android_pppp_av_stream.c
tools/phase3_pppp_probe/run_phase3e_tnp.py
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
yi_native_av_relay.py
yi_native_av_relay_stable.py
yi_native_session_supervisor.py
yi_runtime_lifecycle.py
yi_home/run.sh
tools/prepare_ha_app_context.py
docs/tnp-golden-trace.md
checkpoint.md
```

## Important commits (recent)

```text
1a561997cdb9e9ef3561f657ae32a5c5aed28d60  Mark Phase 6G Frigate integration complete
05790ef...                                      Final Phase 6G validation
fdaeaf88694f62f770664e98d3476b69626bcda4  Expose safe runtime supervisor diagnostics in App logs
ece12824b3411e16459598eeca06a4c19add392c  Expose native worker summary in App diagnostics
06c95a5e2c0ebe49100e4546bcb4b0d629dffaf5  Expose safe PPPP startup diagnostics
c97e5555bdd26ffd72c7df1583d8512ccbef5c15  Gracefully stop relay before process-group fallback
80f3dc88b0484c98e5859196271f909940231c87  Expose relay stage on startup stalls
51de180                                         Expose safe MPEG-TS startup diagnostics
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151  Match official two-stage realtime startup
7c1e6cee8fa517cf4931a951e39200f8fffffb7e  Add worker rebuild/staging helper
ccb2d0b1d2db401105fd1635334dacce157c6415  Expose safe native channel record counters
```

## Recommended next action in a new chat

1. Read this `checkpoint.md` first.
2. Confirm whether the HA App rebuild/restart after commit `ccb2d0b` already happened.
3. If yes, obtain fresh App logs with at least one PTZ startup stall.
4. Inspect `channel1_records`, `channel2_records`, and `channel3_records` from the PTZ shutdown.
5. Make the next code change only after that evidence.

Do not jump directly to FFmpeg flags until the channel-2/channel-3 counter evidence is available.
