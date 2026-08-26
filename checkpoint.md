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
5. Do not send another command until the user reports the current result.
6. Do not ask the user to edit/commit/push source locally when the assistant can edit the repo.
7. Every repo change must be followed by a full checkpoint update.

Canonical laptop checkout:

```text
~/Documents/yi-cam-integration-phase3
```

Canonical HA OS host:

```text
10.0.0.16
```

HA integration path:

```text
/config/custom_components/yi_home
```

Local App build context:

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

Known PTZ example:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

The host port is discovered dynamically through Supervisor; it must not be hardcoded.

Validated Phase 6G behavior:

- live video
- live audio
- detection
- recording
- stream OFF/ON lifecycle
- secret-safe Frigate RTSP export sensor
- Frigate live Opus branch
- recording with source audio copy

Frigate example:

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

Do **not** start Phase 6E while the runtime restart storm remains unresolved.

## Camera IDs relevant to current debugging

```text
e2f22804fecd = PTZ front camera
867ecdee5a36 = pool
6a046d860b2d = separate unstable camera; do not guess its friendly name here
```

Other camera IDs appear in logs, but do not assign friendly names without explicit evidence.

## Official TNP two-stage startup

Golden trace proves the current official client uses a two-stage live start.

Relevant commands:

```text
4881 = SET_RESOLUTION
4882 = SET_RESOLUTION response
9029 = START_REALTIME
768  = START_AUDIO
767  = STOP_LIVE
```

Official Capture A pattern:

```text
T+~3 ms     9029 no.2  use-count=1
             768 no.3

T+~5928 ms  9029 no.11 use-count=2
             768 no.12
```

The second `9029 + 768` is capture-proven, not a blind retry.

Native-worker two-stage implementation:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

The host protocol remains `Y3F1`; the worker derives the first-stage command locally and sends the second pair around 5.9 s later.

Worker build/staging helper:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

File:

```text
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
```

Validated worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

The current App logs prove the second `9029 + 768` pair is sent on all active cameras.

## Native worker exit meanings

```text
40 = PPPP_Connect returned negative
50 = initial PPPP_Write failure
60 = first channel-0 PPPP_Read failed / did not return exactly 8 bytes
61/62/63 = response framing/body/auth failure
71 = media thread creation failure
72 = media reader failure
73 = refresh thread creation failure
```

Observed negative connection value:

```text
0xFFFFF445 = signed -3003
```

Its semantic meaning is not proven. Do not label it timeout/already-connected/etc.

## Supervisor exit/stall codes

```text
74  = EXIT_STARTUP_STALL
75  = generic media stall
81  = native worker failure propagated by relay wrapper
88  = relay runtime error
100 = media_stall_native_header_wait
101 = media_stall_native_payload_wait
102 = media_stall_audio_pipe_write
103 = media_stall_video_pipe_write
104 = media_stall_mux_starting
105 = media_stall_relay_processing
```

Interpretation:

- `74`: no MPEG-TS bytes reached the supervisor inside the 45 s startup window.
- `100`: MPEG-TS had already started and the relay later waited at the next native record header for 12 s.
- `102/103`: a dedicated FFmpeg input writer is blocked by mux/input backpressure.

Do not equate these codes automatically with a dead PPPP connection.

## Graceful shutdown

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

The supervisor first SIGTERMs the relay parent, allowing it to ask the native worker to stop cleanly. Only after a bounded grace period does it fall back to process-group SIGTERM/SIGKILL.

PTZ commonly ends a watchdog generation cleanly:

```text
native_worker_exit=0
mpegts_mux_exit=0
terminate_result=graceful_relay_exit
```

`6a046d860b2d` sometimes still requires process-group termination.

## App build/staging rule

`yi_home/Dockerfile` copies:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

Therefore:

- root-level Python changes require `python3 tools/prepare_ha_app_context.py` before copying staged files into `/addons/yi_home/rootfs/...`;
- `yi_home/run.sh` must be copied directly to `/addons/yi_home/run.sh` and requires App rebuild;
- native C changes require worker compilation/staging.

Do not assume root-level Python edits automatically reach the App build context.

## Safe diagnostics policy

Per-camera full stderr stays private inside the App runtime area. `yi_home/run.sh` mirrors only fixed allowlisted prefixes to the App log.

Never expose arbitrary relay/worker/FFmpeg stderr, command lines, credentials, API tokens, DIDs, device keys, passwords or media payloads.

Useful safe prefixes include:

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
startup_video_frame=
ffmpeg_state=
```

Native channel meaning is established:

```text
channel1 = AAC audio records
channel2 = I-frame video records
channel3 = P-frame video records
```

## Minimal FFmpeg probing experiment — completed and disproved as sole cause

Commit:

```text
328fd031caaee8a13b4b74bc2234f57cb9895874
```

Live-only probe settings were reduced to:

```text
video probesize       = 4096
video analyzeduration = 0
video fpsprobesize    = 0
audio probesize       = 1024
audio analyzeduration = 0
```

The finite validation/file path was untouched.

Deployment was verified on HA by reading the staged file and seeing the new `video_probe_4096/...` marker.

Result: minimal probing **did not eliminate PTZ startup stalls**. PTZ still repeatedly reaches `mpegts_mux=STARTED`, receives native media records, produces no MPEG-TS for 45 s, then emits a valid first TS chunk only after watchdog SIGTERM/EOF.

Therefore large `probesize` alone is not the root cause.

## First-NAL diagnostic — completed

Source commit:

```text
b3fa9d06c9e976447f5f3570d3915f14331c953d
```

The relay reports the first emitted video NAL set on the existing safe `mpegts_mux=STARTED` line.

Observed on stable cameras and PTZ, including failed PTZ startup generations:

```text
first_video_nal_types=7,8,5
first_video_has_sps=1
first_video_has_pps=1
first_video_has_idr=1
```

Thus missing SPS/PPS/IDR is **not** the explanation for code-74 startup stalls.

## First-five record-shape diagnostic — completed

Source commit:

```text
d412e35ef0134c4b83e312aca425e6dde7189b70
```

Safe App allowlist commit:

```text
0d4a6437843864d16beee3d945977567afc72577
```

The diagnostic logs only, for up to the first five decoded video records of each session:

```text
startup_video_frame=<1..5>
channel=<2|3>
frame_type=<I|P>
nal_types=<integers>
nal_count=<integer>
nal_sizes=<integer list>
payload_bytes=<integer>
```

No video bytes are logged.

### Decisive fresh evidence from 2026-08-26 log

Stable `867ecdee5a36` starts immediately with an I-frame:

```text
frame1 channel2 I
NALs 7,8,5
sizes 17,4,15928
payload 15961
```

It then receives ordinary P-frame NAL type 1 records and reaches `media_started=true`.

Stable `51aad28e24ea` similarly starts with:

```text
frame1 channel2 I
NALs 7,8,5
sizes 17,4,39436
payload 39469
```

and reaches `media_started=true`.

Camera `8e97091cc281` proves that beginning with P-frames before the first I-frame is itself valid:

```text
frame1 P type1 size~4901
frame2 P type1 size~5363
frame3 P type1 size~5269
frame4 P type1 size~4803
frame5 I NALs 7,8,5 sizes 16,4,240005
```

That generation reaches `media_started=true` with a first TS chunk of 940 bytes.

### PTZ failed generation

PTZ `e2f22804fecd` shows five early P records:

```text
frame1..5 = channel3 / P / NAL type1
payloads roughly 3.1-3.6 KB
```

After the reorder buffer reaches the first I-frame, the relay reports:

```text
first_video_nal_types=7,8,5
SPS=1 PPS=1 IDR=1
```

Yet the generation still ends after 45 s with:

```text
startup_stall code=74
channel1=62
channel2=1
channel3=77
```

and only after SIGTERM does FFmpeg emit the first TS chunk (`5640` bytes), then both native worker and mux exit 0.

### PTZ successful generation with essentially the same opening shape

A later PTZ generation again starts with five P/type-1 records of similar size, again reports first emitted I-frame NALs `7,8,5`, but this time FFmpeg emits a TS chunk (`2444` bytes) and the supervisor reports:

```text
media_started=true
```

Later that successful PTZ generation can still fail separately with code `100` (`native_header_wait`) after roughly 1.09 MB forwarded and hundreds of records.

### `6a046d860b2d` also reproduces both outcomes

`6a` can start with several P/type-1 records, later receive a normal I-frame `7,8,5`, and either:

- hit startup code `74` with first TS appearing only at shutdown, or
- reach `media_started=true` and later hit code `100`/`102`.

This is important because the startup mux issue is not unique to the PTZ camera.

## Current interpretation of the startup stall

The following explanations are now strongly weakened or disproved:

- no P-frames;
- missing SPS;
- missing PPS;
- missing IDR;
- simply starting with P frames before the first I frame;
- I-frame size alone;
- large FFmpeg `probesize` alone;
- a simple synchronous Python video/audio pipe deadlock (the live wrapper already uses independent input writer threads and many startup stalls report the main relay back at `native_header_read`).

Because failed and successful generations can present essentially the same H264 record/NAL opening pattern, **do not add AUD separators yet**. There is not enough evidence that access-unit boundary recognition is the root cause.

The strongest next target is **FFmpeg's internal transition from elementary-stream input parsing to output/mux initialization**.

## New safe FFmpeg state diagnostic — current repo head

### New file

```text
yi_ffmpeg_state_wrapper.py
```

Commit:

```text
daa6ec85306676ec130656702077c840d8ccaaa5
```

### App integration / safe allowlist

`yi_home/run.sh` commit:

```text
dbafcdc62df3c09f7e90db9b89d701afd00e12a1
```

### Design

The App resolves the real FFmpeg executable before prepending a private wrapper directory to `PATH` and exports the absolute real path as `YI_REAL_FFMPEG`.

The wrapper is transparent for all non-target FFmpeg calls:

```text
os.execv(real_ffmpeg, original_args)
```

It activates only for the known YI live stdout mux shape, requiring markers such as:

```text
pipe:1
-bsf:v
-bsf:a
-flush_packets
setts=...
```

The finite validation path does not use the SETTS bitstream filters, so it is passed directly to real FFmpeg unchanged.

For the YI live mux only, the wrapper changes **only logging verbosity**:

```text
-loglevel warning -> -loglevel info
```

No codec, demuxer, muxer, probe, timestamp, queue, interleave, map, stream, timeout or media argument is changed.

The wrapper creates a small stderr-filter child and then `exec`s the real FFmpeg in the original process. This is deliberate: the process tracked by the relay/supervisor remains the actual FFmpeg PID rather than a long-lived wrapper parent.

The filter consumes all FFmpeg stderr but emits only fixed secret-safe markers. Raw FFmpeg stderr is never mirrored into the App log.

### Safe markers expected

```text
ffmpeg_state=diagnostic_active
ffmpeg_state=video_input_open
ffmpeg_state=video_stream_info
ffmpeg_state=audio_input_open
ffmpeg_state=audio_stream_info
ffmpeg_state=stream_mapping_ready
ffmpeg_state=output_mpegts_ready
```

At FFmpeg stderr EOF it emits a fixed boolean summary:

```text
ffmpeg_state=stderr_eof;video_input=0|1;video_stream=0|1;audio_input=0|1;audio_stream=0|1;mapping=0|1;output=0|1
```

`yi_home/run.sh` now allowlists only lines beginning:

```text
[phase3g-relay] ffmpeg_state=
```

No arbitrary FFmpeg line is exposed.

### What the next test must answer

Compare at least:

1. one PTZ generation ending in startup `74`;
2. one PTZ generation reaching `media_started=true`;
3. one stable camera generation.

Interpret the deepest marker reached before first TS:

- only `video_input_open/video_stream_info` -> FFmpeg has not completed audio input discovery;
- both inputs/stream-info but no `stream_mapping_ready` -> FFmpeg is stuck before mapping/output setup;
- mapping but no `output_mpegts_ready` -> stuck between mapping and mux header/output initialization;
- `output_mpegts_ready` but still no `mpegts_stdout_first_chunk_bytes` -> mux is initialized but not writing packets; investigate timestamp/interleave/packet release next;
- failed and successful sessions reach identical FFmpeg milestones -> add finer safe FFmpeg state diagnostics before changing media behavior.

## Separate post-start failure modes

Do not merge startup code `74` with post-start stalls.

PTZ can successfully stream and later hit:

```text
code100 native_header_wait
```

Fresh example:

```text
forwarded_bytes ~= 1,093,408
channel1=215
channel2=7
channel3=263
```

Then graceful shutdown reports about 1.115 MB pumped and clean worker/mux exit.

`6a046d860b2d` separately shows:

```text
code100 native_header_wait
code102 audio_pipe_write
```

and sometimes needs process-group SIGTERM/SIGKILL.

Fixing startup mux behavior will not automatically fix these runtime failures.

## Integration sensor note

The PTZ Frigate RTSP sensor briefly appeared missing after App updates. Reloading the HA integration recreated/registered it and it displayed a feed. This was an HA integration/entity refresh issue, not evidence that RTSP export for PTZ was absent.

Do not modify the sensor registry unless the issue returns and is proven persistent.

## Current deployment status

Deployed and validated before the latest diagnostic change:

- two-stage native worker;
- minimal FFmpeg probing;
- safe worker/channel counters;
- first-NAL startup diagnostic;
- first-five video record-shape diagnostic;
- safe `startup_video_frame=` App allowlist.

**Not yet deployed at the time of this checkpoint update:**

```text
daa6ec85306676ec130656702077c840d8ccaaa5  yi_ffmpeg_state_wrapper.py
dbafcdc62df3c09f7e90db9b89d701afd00e12a1  enable wrapper + ffmpeg_state allowlist in run.sh
```

This checkpoint commit itself follows those source changes.

## Next deployment

This is a Python + `run.sh` App change; no native worker rebuild is needed.

Laptop deployment must:

1. pull branch;
2. `py_compile` the new wrapper;
3. run `tools/prepare_ha_app_context.py` so the root-level wrapper is staged into `yi_home/rootfs/opt/yi-home/app/`;
4. copy the staged wrapper and `yi_home/run.sh` to the HA App build context.

HA then needs one App rebuild/restart command.

After restart, verify the App boot log contains:

```text
Safe live FFmpeg state diagnostics enabled; raw_ffmpeg_stderr_exposed=false.
```

Then collect enough App log to compare FFmpeg milestones for failed/successful sessions.

## Do not do yet

- Do not increase the 45 s startup timeout as a workaround.
- Do not increase the 12 s stall timeout as a workaround.
- Do not add blind retries.
- Do not add another `9029` request without new capture evidence.
- Do not add AUD separators yet.
- Do not revert to large FFmpeg probe windows.
- Do not change the proven finite-file path.
- Do not start Phase 6E.
- Do not reopen solved Frigate networking/audio/export unless a regression is demonstrated.
- Do not infer the semantic meaning of PPPP `-3003` without evidence.
- Do not expose raw FFmpeg/worker/relay stderr.
- Do not guess Supervisor private filesystem paths.

## Key files

```text
tools/phase3_pppp_probe/android_pppp_av_stream.c
tools/phase3_pppp_probe/run_phase3e_tnp.py
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
yi_live_relay.py
yi_native_av_relay.py
yi_native_av_relay_stable.py
yi_native_session_supervisor.py
yi_runtime_lifecycle.py
yi_ffmpeg_state_wrapper.py
yi_home/run.sh
tools/prepare_ha_app_context.py
custom_components/yi_home/sensor.py
docs/tnp-network-golden-trace.md
checkpoint.md
```
