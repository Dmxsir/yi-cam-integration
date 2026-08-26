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

Stable Frigate source:

```text
rtsp://<HA-host>:<mapped-port>/yi_<12-char-stream-prefix>
```

Known PTZ example:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

The mapped RTSP host port is discovered through Supervisor; it is not hardcoded in production.

Previously validated:

- live video
- live audio
- detection
- recording
- stream OFF/ON lifecycle
- secret-safe Frigate export
- App-owned go2rtc publication

Do **not** start Phase 6E while the restart/stall issue below is unresolved.

## PTZ identity — important distinction

The PTZ uses a **20-character stable ID** internally:

```text
e2f22804fecdbd8c3561
```

Its public stream/log diagnostic prefix is only the first 12 characters:

```text
e2f22804fecd
```

Therefore:

```text
stable_id = e2f22804fecdbd8c3561
stream_id = yi_e2f22804fecd
RTSP path = /yi_e2f22804fecd
run.sh diagnostic camera label = e2f22804fecd
```

`yi_runtime_lifecycle.py` stores logs by full stable ID, but `yi_home/run.sh` intentionally prints only `path.stem[:12]` in the App log.

This distinction is critical. Never compare `--stable-id`, `YI_FFMPEG_STABLE_ID`, runtime log filename, or internal camera key against the 12-character stream prefix.

Other known diagnostic prefixes:

```text
867ecdee5a36 = pool prefix
6a046d860b2d = separate unstable camera prefix
```

Do not invent full stable IDs for those without evidence.

## Golden PTZ baseline — proven stable runtime

Library log from 2026-08-23 proves the PTZ stable ID `e2f22804fecdbd8c3561` ran continuously for **600 seconds** with:

```text
generation=1
restart_count=0
runtime_state=running
media_publisher_attached=true
published_bytes=81264640
```

The same run reported:

```text
stream_id=yi_e2f22804fecd
publisher_ready=true
producer_media_ready=true
media_started=true; first_chunk_bytes=65536
```

and then continuous MPEG-TS progress through ~80 MB.

This is the canonical working baseline showing that the architecture and PTZ can operate stably for at least 10 minutes without a restart.

## Historical regression review — 2026-08-26

Compared Phase-6G completion commit:

```text
1a561997cdb9e9ef3561f657ae32a5c5aed28d60
```

to current branch.

Important findings:

1. The first commit after the known working Phase-6G point was `fdaeaf88694f62f770664e98d3476b69626bcda4`, which only exposed safe runtime diagnostics to App logs. It did not introduce a new media path.
2. `yi_runtime_lifecycle.py` has not changed across the investigated regression window.
3. The App Dockerfile already pinned FFmpeg 6.0.1 with a SHA256 in the working baseline, so this is not explained by a silent FFmpeg major-version upgrade.
4. The later minimal-probe FFmpeg change and two-stage TNP change were made **after** the restart/stall issue was already under investigation. They can affect frequency/shape but cannot by themselves explain the original appearance of the issue.
5. Current PTZ behavior is intermittent: the same build can have Class-A startup stalls and also successful `media_started=true` generations.

Conclusion: there is no evidence for one simple source commit that deterministically "broke the feed". Current evidence is more consistent with intermittent/state-dependent behavior in the camera/TNP/FFmpeg pipeline.

## TNP/PPPP two-stage startup — current implementation

Official capture proves:

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

Implementation commit:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

Worker build/staging helper:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

Validated worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

Do not add blind extra `9029` requests.

Historical working worker behavior at `1a561997...` used the host-supplied sequence directly:

```text
4881
9029 use-count=2
768
```

without the later 5.9-second refresh. Keep this as a controlled rollback candidate only if the current video-only A/B does not isolate the fault.

## Native worker exit meanings

```text
40 = PPPP_Connect negative
50 = initial PPPP_Write failure
60 = first channel-0 PPPP_Read failed / not exactly 8 bytes
61/62/63 = response framing/body/auth failure
71 = media thread creation failure
72 = media reader failure
73 = refresh thread creation failure
```

Observed connection value:

```text
0xFFFFF445 = signed -3003
```

Its semantic meaning is unproven. Do not label it timeout/already-connected/etc.

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

Startup timeout is 45 s; post-start stall timeout 12 s. Do not increase them as a workaround.

## App build/staging rule

`yi_home/Dockerfile`:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

Therefore:

- root Python change => run `python3 tools/prepare_ha_app_context.py`, then copy staged file(s) under `/addons/yi_home/rootfs/...`, then rebuild App;
- `yi_home/run.sh` can be copied directly and needs rebuild;
- C change => compile/stage worker;
- never assume root-level Python is already inside the App context.

## Graceful shutdown

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

Supervisor first SIGTERMs relay parent so it can send STOP/BREAK/FORCECLOSE and close PPPP cleanly. Process-group TERM/KILL is fallback only after grace timeout.

PTZ usually exits gracefully. `6a046d860b2d` sometimes still requires process-group fallback.

## Safe diagnostics policy

`yi_home/run.sh` mirrors only fixed allowlisted prefixes from `/data/runtime/*.log`.

Allowed evidence includes:

- PPPP return codes
- TNP response version/command/auth result
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

## FFmpeg live path — working baseline vs current

Working Phase-6G baseline (`1a561997...`) live input probing:

```text
video probesize=262144
video analyzeduration=500000
video thread_queue_size=512
video -fflags +nobuffer
video rate=20

audio probesize=32768
audio analyzeduration=200000
audio thread_queue_size=512
```

Current minimal-probe diagnostic configuration from commit `328fd031...`:

```text
video probesize=4096
video analyzeduration=0
video fpsprobesize=0

audio probesize=1024
audio analyzeduration=0
```

Both use stream copy, SETTS, MPEG-TS, `-flush_packets 1`, `-muxdelay 0`, `-muxpreload 0`, and resend headers.

Minimal probing did not remove Class A and was introduced after the issue was already present. Do not treat probing alone as root cause.

## Key H264 diagnostics

### First H264 NAL diagnostic

Commit:

```text
b3fa9d06c9e976447f5f3570d3915f14331c953d
```

Failed PTZ generations still show:

```text
first_video_nal_types=7,8,5
SPS=1 PPS=1 IDR=1
```

Missing SPS/PPS/IDR is not primary startup cause.

### First-five-record H264 shape diagnostic

Commits:

```text
d412e35ef0134c4b83e312aca425e6dde7189b70
0d4a6437843864d16beee3d945977567afc72577
5fc8df9d764903f7ac3d4aea18a6044123f18a00
```

Successful and failed sessions can begin with the same general pattern: several P records (`NAL 1`) before I record (`7,8,5`). Stable cameras can also do this. Do not inject AUD without new evidence.

## FFmpeg state diagnostics — decisive Class-A evidence

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

Then remains silent for 45 s. On SIGTERM, first MPEG-TS chunk appears immediately and mux/worker can exit cleanly.

Therefore Class A is after both inputs are opened/identified and after MPEG-TS output/mapping are ready, but before the first output packet is emitted.

Strongly ruled out for Class A:

- no P-frames
- no SPS/PPS/IDR
- large probing window alone
- failure to identify H264
- failure to identify AAC
- failure to create MPEG-TS output
- failure to map streams

Leading area: FFmpeg packet scheduling / A-V interleave / timestamp behavior.

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
first TS immediately appears
```

Target of current A/B experiment.

### Class B — no initial I-frame

Observed generations with channel1/channel3 activity but `channel2_records=0`. Exclude those from Class-A A/B judgment.

### Class C — native worker exit 60

```text
native_worker_exit=60
relay_exit_rc=81
```

Early PPPP/TNP failure; separate from FFmpeg Class A. Exclude from A/B judgment.

### Class D — post-start native header starvation

After successful publication PTZ can later hit code 100 `qemu_alive_ffmpeg_alive_native_header_wait`. Separate source/session starvation state.

## `6a046d860b2d` independently unstable

Observed:

- startup 74
- post-start 100 native-header wait
- 102 audio-pipe write stall
- worker 60
- PPPP connect negative / worker 40
- occasional process-group TERM/KILL

Do not treat all `6a` failures as PTZ root cause.

## Current temporary A/B — PTZ MPEG-TS video-only output

Goal: test whether mapped AAC/A-V interleave is responsible for Class A while keeping AAC input consumed so the relay's audio writer does not block.

For PTZ live only:

- H264 input unchanged;
- AAC input remains open and consumed;
- remove only output `-map 1:a:0`;
- remove `-bsf:a` because audio is not mapped;
- H264 stream-copy, no transcoding;
- MPEG-TS output video-only;
- PPPP/TNP, worker, two-stage 9029/768, reorder and watchdogs unchanged.

Safe activation markers:

```text
ffmpeg_state=ptz_detection=stable_id_env
ffmpeg_state=ptz_video_only_ab_active
```

Shutdown summary for a valid activated PTZ generation must include:

```text
video_only=1
```

Other cameras must remain `ptz_detection=none` and `video_only=0`.

## Why all prior video-only attempts were invalid

Previous detector attempts:

```text
8db7d48162fee17b89e4b78bc247f7004a066ad6
0fecfe106b5f06c17901e3eb4658aeb8927d3ed6
3f34ee8d657127aa9e7fccaa4e96c9db6ef45899
198f5154d598678ecd5d15a6d4e3be431397c830
8e11d5b2cd08753d728ac4d8f8078424dc43d095
3b0b5225ae442cf15ce64fb7b78840859c8716a1
```

All prior runs logged `ptz_detection=none` and `video_only=0`, so none was a valid A/B result.

Root cause discovered 2026-08-26:

- wrapper target was incorrectly set to the 12-character stream prefix `e2f22804fecd`;
- actual `YI_FFMPEG_STABLE_ID` / `--stable-id` value is the full 20-character `e2f22804fecdbd8c3561`;
- runtime stderr filename also uses the full stable ID;
- `run.sh` truncates the camera label to 12 characters only when mirroring safe diagnostics.

Thus env inheritance and staging were not disproven by `ptz_detection=none`; the comparison target itself was wrong.

## Current source fix — full PTZ stable ID

Commit:

```text
523a30687f578e28781251d8e7f7e4a6965b6e86  Fix PTZ A/B stable-id match
```

Changed file:

```text
yi_ffmpeg_state_wrapper.py
```

Corrected constants:

```text
PTZ_VIDEO_ONLY_STABLE_ID_TEXT = e2f22804fecdbd8c3561
PTZ_VIDEO_ONLY_LOG_NAME       = e2f22804fecdbd8c3561.log
```

The existing stable relay already exports:

```text
YI_FFMPEG_STABLE_ID=<full stable_id>
```

No further stable-relay code change is required for this correction.

## Interpretation criteria after real activation

Only generations containing both:

```text
camera=e2f22804fecd ... ffmpeg_state=ptz_detection=stable_id_env
camera=e2f22804fecd ... ffmpeg_state=ptz_video_only_ab_active
```

count as the real A/B experiment.

If valid PTZ `video_only=1` generations produce TS promptly/reliably, strong evidence points to mapped AAC, A/V timestamp relationship or A/V interleave/output scheduling.

If valid `video_only=1` generations still reach video/output readiness and stall until EOF, mapped AAC is not sufficient to explain Class A. Next controlled comparison should restore the known-working media path in stages, starting with the historical worker startup sequence and/or the Phase-6G FFmpeg live parameters, one variable at a time.

Exclude channel2=0 and worker40/60 generations from the A/B verdict.

## Current deployment state

At this checkpoint:

- normal FFmpeg state diagnostics are deployed and proven;
- H264 shape diagnostics are deployed and proven;
- stable relay env-export code is present in HA build context and was verified with `grep`;
- wrapper env-detection code is present in HA build context and was verified with `grep`;
- prior `ptz_detection=none` is now explained by comparing against the wrong 12-character prefix;
- fix commit `523a3068...` is in GitHub and **not yet confirmed deployed to HA**;
- only `yi_ffmpeg_state_wrapper.py` needs staging/copy for this source change;
- no native worker rebuild is required;
- `run.sh` needs no change because `ffmpeg_state=` is already allowlisted.

## Next deployment step

Laptop: pull, syntax-check wrapper, prepare App context, copy staged wrapper to HA App context in one command.

HA: rebuild/restart `local_yi_home` in one command.

First proof required from the next App log:

```text
camera=e2f22804fecd ... ffmpeg_state=ptz_detection=stable_id_env
camera=e2f22804fecd ... ffmpeg_state=ptz_video_only_ab_active
```

Only then judge whether Class A still occurs under `video_only=1`.

## Do not do next

- Do not start Phase 6E.
- Do not increase timeouts.
- Do not add blind retries/additional 9029.
- Do not inject AUD yet.
- Do not reopen solved Frigate networking/audio/export.
- Do not interpret any prior `video_only=0` run as evidence for or against AAC/interleave.
- Do not revert multiple historical changes at once; use one controlled variable per experiment.
