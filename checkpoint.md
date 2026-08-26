# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-08-26_  
_Branch: `phase-3-linux-pppp`  
_Repository: `Dmxsir/yi-cam-integration`

## Purpose

This is the canonical handoff document for continuing the YI camera reverse-engineering / Home Assistant project after context loss or in a new chat.

**Mandatory workflow rule:** every repository source change must also update this `checkpoint.md` with current code state, deployment state, evidence, conclusions and next step.

## User workflow constraint

The user wants a minimal deployment workflow:

1. Assistant edits GitHub directly.
2. User gets **one command for the laptop**.
3. User gets **one command for Home Assistant**.
4. Do not dump long command sequences; wait for results before the next step.

Canonical paths:

```text
repo: Dmxsir/yi-cam-integration
branch: phase-3-linux-pppp
laptop checkout: ~/Documents/yi-cam-integration-phase3
HA OS host: 10.0.0.16
HA integration: /config/custom_components/yi_home
HA App source: /addons/yi_home
App slug: local_yi_home
```

Public names:

```text
App: YI RTSP
Integration: YI Camera Connect
```

Internal identifiers remain `yi_home`.

## Architecture

```text
YI camera
 -> PPPP/TNP native session
 -> AArch64 native worker under QEMU
 -> H264 + AAC records
 -> Python relay
 -> FFmpeg MPEG-TS mux
 -> App-owned go2rtc / RTSP
 -> HA mapped RTSP port
 -> Frigate / HA consumers
```

The App owns camera runtime lifecycle. Frigate is a consumer only.

## Phase 6G status

Phase 6G Frigate integration/export is COMPLETE. Do not reopen it unless a regression is proven.

Stable external stream format:

```text
rtsp://<HA-host>:<mapped-port>/yi_<stable-prefix>
```

Known PTZ example:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

The host RTSP port is discovered through Supervisor, not hardcoded.

Frigate live audio uses an Opus branch while recording preserves source audio:

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
- secret-safe RTSP/Frigate export

Do **not** begin Phase 6E while runtime restart instability remains unresolved.

## Relevant camera IDs

```text
e2f22804fecd = PTZ front camera
867ecdee5a36 = pool
6a046d860b2d = unstable camera; friendly-name mapping not fixed here
```

Do not guess other mappings without evidence.

## TNP two-stage startup — proven and deployed

Official current-client golden trace proves:

```text
T+~3 ms     9029 no.2  use-count=1
             768 no.3

T+~5928 ms  9029 no.11 use-count=2
             768 no.12
```

Relevant commands:

```text
4881 = SET_RESOLUTION
4882 = SET_RESOLUTION response
9029 = START_REALTIME
768  = START_AUDIO
767  = STOP_LIVE
```

Implementation commit:

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151
```

It keeps the existing host-worker `Y3F1` protocol and derives the first-stage and refresh commands inside the native worker.

Worker staging helper:

```text
7c1e6cee8fa517cf4931a951e39200f8fffffb7e
```

Validated worker SHA-256:

```text
67d12d6e56746a67d306a0ebff8ef07ee02aaef51954b38fe0e0383c5229fa5a
```

Runtime logs prove the second `9029 + 768` pair is actually sent.

## Worker / supervisor exit meanings

Native worker:

```text
40 = PPPP_Connect returned negative
50 = initial PPPP_Write failure
60 = first channel-0 PPPP_Read failed / not exactly 8 bytes
61/62/63 = response framing/body/auth failure
71 = media thread creation failure
72 = media reader failure
73 = refresh-thread creation failure
```

Observed negative connect value:

```text
0xFFFFF445 = signed -3003
```

Its semantic meaning is not proven. Do not label it timeout/already-connected/etc.

Supervisor / relay diagnostic codes:

```text
74  = startup stall: no MPEG-TS output inside 45 s
81  = native worker failure propagated by wrapper
88  = relay runtime error
100 = native_header_wait
101 = native_payload_wait
102 = audio_pipe_write
103 = video_pipe_write
104 = mux_starting
105 = relay_processing
```

These codes do not by themselves prove the PPPP connection is dead.

## Channel semantics

Current native stream channels are established as:

```text
channel1 = AAC audio
channel2 = I-frame video
channel3 = P-frame video
```

## Graceful shutdown

Commit:

```text
c97e5555bdd26ffd72c7df1583d8512ccbef5c15
```

Supervisor first SIGTERMs the relay parent so it can request worker STOP/BREAK/FORCECLOSE. Process-group SIGTERM/SIGKILL is fallback only.

PTZ generally exits cleanly after watchdog termination:

```text
native_worker_exit=0
mpegts_mux_exit=0
terminate_result=graceful_relay_exit
```

`6a046d860b2d` frequently needs process-group fallback.

## App build/staging rule

`yi_home/Dockerfile` uses:

```dockerfile
COPY rootfs/ /
COPY run.sh /run.sh
```

Therefore:

- root Python changes require `python3 tools/prepare_ha_app_context.py` before copying staged files to `/addons/yi_home/rootfs/...`;
- `yi_home/run.sh` is copied directly to `/addons/yi_home/run.sh`;
- C worker changes require compilation/staging;
- App changes require `ha apps rebuild local_yi_home` and restart.

Do not assume root Python edits automatically reach the App build context.

## Secret-safety rule

App logs may expose only fixed, reviewed prefixes. Never mirror arbitrary worker/relay stderr, credentials, DID/UID values, API tokens or video/audio payload bytes.

Current useful safe diagnostics include:

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

## Main PTZ problem: repeated startup stall

Typical PTZ failed generation:

```text
TNP auth PASS
media readers STARTED
initial_av_delta_ms ~= tens of milliseconds
mpegts_mux=STARTED
45 s without TS output
startup_stall code=74
SIGTERM relay parent
first MPEG-TS chunk appears only after shutdown begins
worker/mux exit 0
```

Channel counters repeatedly prove media arrives during the 45 s wait. Examples across recent logs include:

```text
30 / 1 / 35
19 / 1 / 23
36 / 1 / 27
53 / 1 / 59
57 / 2 / 56
90 / 3 / 104
84 / 1 / 108
55 / 2 / 69
```

Format is `audio / I / P`.

Therefore the startup failure is **not caused by absent P-frames**.

## Minimal FFmpeg probing experiment — deployed, negative result

Commit:

```text
328fd031caaee8a13b4b74bc2234f57cb9895874
```

Live-only options became:

```text
video probesize=4096
video analyzeduration=0
video fpsprobesize=0
audio probesize=1024
audio analyzeduration=0
```

Finite file-validation path was left unchanged.

Deployment was verified in HA by grepping the staged source.

Result: **minimal probing did not eliminate PTZ startup stalls**. The same 45 s -> SIGTERM -> immediate TS-output pattern remains.

Do not keep lowering probe values as the next move.

## First-frame NAL diagnostic — deployed and decisive

Commit:

```text
b3fa9d06c9e976447f5f3570d3915f14331c953d
```

It logs the NAL types of the first reordered video frame via the existing safe `mpegts_mux=STARTED` prefix.

Fresh logs show stable cameras start with:

```text
first_video_nal_types=7,8,5
first_video_has_sps=1
first_video_has_pps=1
first_video_has_idr=1
```

Crucially, failed PTZ generations show **the same exact first-frame set**:

```text
7 = SPS
8 = PPS
5 = IDR
```

and still reach code 74 before TS appears only on shutdown.

Therefore the hypothesis “failed PTZ startup is missing SPS/PPS/IDR” is **DISPROVED**.

Do not spend more time testing only presence/absence of first-frame SPS/PPS/IDR.

## New leading hypothesis: H264 record/access-unit shape

Because PTZ and stable cameras all have SPS/PPS/IDR but behave differently, the next comparison is the **shape of the first few H264 records**, not only NAL presence.

Questions to answer:

- Are PTZ and stable cameras producing the same NAL count per record?
- Are SPS/PPS/IDR and following slice sizes materially different?
- Are early channel-3 records multi-slice or unusually framed?
- Is FFmpeg failing to recognize access-unit boundaries for PTZ until EOF closes the raw H264 pipe?

If record shape differs in a way consistent with missing AU boundaries, a later experiment may inject H264 AUD NALs between records **without transcoding**. Do not implement AUD injection before the diagnostic evidence exists.

## New startup record-shape diagnostic — source head, not yet deployed

Source commits:

```text
d412e35ef0134c4b83e312aca425e6dde7189b70  Expose early H264 record shape diagnostics
0d4a6437843864d16beee3d945977567afc72577  Surface safe early H264 record diagnostics
```

Changed files:

```text
yi_live_relay.py
yi_home/run.sh
```

Behavior is diagnostic only. It does **not** change TNP commands, worker behavior, FFmpeg options, timestamps, timeouts, retries, watchdogs, reorder behavior or media bytes.

Each relay process logs at most the first **5 decoded video records**:

```text
[yi-live-relay] startup_video_frame=<1..5>;
channel=<2|3>;
frame_type=<I|P>;
nal_types=<integer list>;
nal_count=<count>;
nal_sizes=<NAL payload sizes only>;
payload_bytes=<total Annex-B payload bytes>
```

No video contents are logged. `yi_home/run.sh` exposes only the exact safe prefix:

```text
[yi-live-relay] startup_video_frame=
```

### What to compare after deployment

Capture a log containing:

1. at least one stable camera startup;
2. at least one PTZ generation that ends in code 74;
3. if possible, a PTZ generation that reaches `media_started=true`.

Compare frames 1-5 for:

```text
channel
frame_type
nal_types
nal_count
nal_sizes
payload_bytes
```

If PTZ failed generations show a repeatable access-unit shape difference, use that evidence to decide whether an AUD-boundary experiment is justified.

## PTZ has separate pre-media failures too

The PTZ restart storm is not only code 74.

Recent log also contains:

```text
PPPP_Connect_rc_hex=0xFFFFF445
native_worker_exit=40
```

and consecutive generations where PPPP connect succeeds but the worker exits `60` before authentication/media.

These are separate upstream PPPP/TNP failures and must not be confused with the FFmpeg/startup-buffering code-74 path.

Do not assume one fix will resolve all PTZ restarts.

## PTZ post-start runtime stall is separate

Even after successful MPEG-TS publication the PTZ can later hit:

```text
code=100
qemu_alive_ffmpeg_alive_native_header_wait
```

It can have already forwarded >1 MB and accumulated hundreds of records before this happens.

That is source/session starvation after startup, not the same problem as code 74.

## `6a046d860b2d` is independently unstable

Observed failure modes include:

```text
74  startup stall
81  native worker exit (including worker 60)
100 native_header_wait after media started
102 audio_pipe_write after multi-megabyte publication
105 relay_processing
```

Examples show thousands of audio records and hundreds of video records before some code-102 failures. Shutdown often needs group SIGTERM/SIGKILL.

Do not merge its behavior with the PTZ startup problem without evidence.

## Home Assistant RTSP sensor observation

After an App update, the PTZ Frigate/RTSP sensor did not initially appear. Reloading the **YI Camera Connect integration** caused the sensor to appear and it showed a feed.

The sensor implementation creates runtime + Frigate RTSP sensors for every coordinator `stable_id`; it is not intentionally suppressed by runtime instability.

No Entity Registry modification was required.

## Current deployment status

As of this checkpoint:

**Deployed and verified:**

```text
two-stage native worker
channel counters
minimal FFmpeg probing
first-frame NAL diagnostic b3fa9d06...
```

**In GitHub but NOT YET confirmed deployed:**

```text
d412e35e... yi_live_relay.py early record-shape diagnostics
0d4a6437... yi_home/run.sh safe allowlist for those diagnostics
```

The next deployment must stage root Python, copy staged `yi_live_relay.py`, copy `yi_home/run.sh`, rebuild and restart the App.

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
yi_home/run.sh
tools/prepare_ha_app_context.py
docs/tnp-network-golden-trace.md
checkpoint.md
```

## Important recent commits

```text
1d269056f6a6d86157b3ba59e1cdbb3b9bae3151  two-stage official-style 9029/768 startup
7c1e6cee8fa517cf4931a951e39200f8fffffb7e  worker build/staging helper
c97e5555bdd26ffd72c7df1583d8512ccbef5c15  graceful relay-first shutdown
80f3dc88b0484c98e5859196271f909940231c87  startup relay-stage diagnostic
51de1808d318ae6e6f34f47cf9936aef44b40513  MPEG-TS startup diagnostics
ccb2d0b1d2db401105fd1635334dacce157c6415  channel record counters
328fd031caaee8a13b4b74bc2234f57cb9895874  minimal live FFmpeg probing
b3fa9d06c9e976447f5f3570d3915f14331c953d  first-frame NAL presence diagnostic
d412e35ef0134c4b83e312aca425e6dde7189b70  first-five H264 record-shape diagnostic
0d4a6437843864d16beee3d945977567afc72577  App safe allowlist for record-shape diagnostic
```

## What NOT to do next

Do not:

- increase the 45 s startup timeout;
- add blind retries;
- add more 9029 commands;
- change TNP startup again without new protocol evidence;
- lower FFmpeg probing further as the first response;
- assume missing SPS/PPS/IDR — it is disproved;
- inject AUDs before the new record-shape comparison is collected;
- merge code 74, worker 40/60, code 100 and code 102 into one root cause;
- start Phase 6E;
- reopen solved Frigate networking/audio/export issues without regression evidence;
- ask the user to edit/commit/push source locally;
- expose arbitrary runtime stderr or secrets.

## Immediate next step

Deploy the two diagnostic source commits, let the App run long enough to capture several PTZ generations, then compare `startup_video_frame=1..5` between stable and failed PTZ sessions.

No behavioral fix should be selected until those record-shape diagnostics are reviewed.
