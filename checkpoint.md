# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-08-26_  
_Branch: `phase-3-linux-pppp`  
_Repository: `Dmxsir/yi-cam-integration`

## Purpose

Canonical handoff/context document for the YI camera reverse-engineering / Home Assistant project.

**Mandatory workflow:** every repository source change must update this checkpoint with source state, deployment state, evidence, conclusions and next step.

## User workflow constraint

1. Assistant edits GitHub directly.
2. User gets at most one laptop command at a time.
3. User gets at most one Home Assistant command at a time.
4. Do not ask the user to edit/commit/push source locally when GitHub can be updated directly.
5. Do not start the next command until the previous result is reported.

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

## Architecture

```text
YI camera
 -> PPPP/TNP native session
 -> AArch64 native worker under QEMU
 -> H264 + AAC native records
 -> Python relay
 -> FFmpeg MPEG-TS mux
 -> App-owned go2rtc / RTSP
 -> HA OS mapped RTSP port
 -> Home Assistant / external Frigate consumers
```

The App owns the camera runtime and publication lifecycle. Home Assistant and Frigate consume the App-owned stream; they do not open independent YI PPPP sessions.

## Phase 6G

Phase 6G Frigate integration/export is COMPLETE and must not be reopened absent a real regression.

Validated topology includes live video, live audio, detection, recording, stream OFF/ON lifecycle, dynamic Supervisor RTSP host-port discovery and secret-safe Frigate export.

Known PTZ stream example:

```text
stable_id = e2f22804fecdbd8c3561
stream_id = yi_e2f22804fecd
RTSP path = /yi_e2f22804fecd
```

Do not confuse the full 20-character stable ID with the 12-character stream/log prefix.

## Historical HA OS working baseline

The strongest working baseline is the HA OS PTZ-only 60-minute validation recorded by commit:

```text
9c554a1655a058669d1844a8e353b7f27b6d4af5
Advance HA OS media gates after async writer pass
```

Recorded result:

```text
PTZ-only long-run: 60 minutes
restart_count=0
no last exit code
publisher remained attached
published bytes continued increasing
```

The later Phase-6G completion commit:

```text
1a561997cdb9e9ef3561f657ae32a5c5aed28d60
Mark Phase 6G Frigate integration complete
```

still used the same media-runtime source as that 60-minute gate. The changes between `9c554a16` and `1a561997` were Home Assistant/Frigate/UI/export work, not changes to the native worker, relay or supervisor.

Therefore `1a561997` is the canonical source snapshot for a controlled media-runtime rollback while retaining the completed Phase-6G product state around it.

## Regression investigation — 2026-08-26

### Current failures are not dependent on multiple YI streams

A controlled test disabled every App-owned camera stream except PTZ. PTZ initially published normally to both Home Assistant and Frigate, then failed while it was still the only active YI runtime.

Observed sequence:

```text
media_stall_detected
qemu_alive_ffmpeg_alive_native_header_wait
diagnostic_exit_code=100
forwarded_bytes=75951060

native_worker_exit=0
mpegts_mux_exit=0
video_frames=22286
audio_frames=17456

next generation: native_worker_exit=60
next valid generation: startup_stall exit=74
next generation: native_worker_exit=40
later generation: media_started=true
```

Conclusion: multi-camera concurrency/load is not a necessary condition for the PTZ restart storm. It may still influence frequency, but it is not the sole cause.

### Official YI application check

During one failure window the official app also briefly failed to stream while the custom PPPP session was active. This is not valid proof of an upstream camera/service outage because two direct clients may contend for a live session.

After the YI RTSP PTZ stream was switched OFF, the official YI application immediately streamed correctly. No long independent official-app soak was performed, so do not overstate this as proof that the camera/cloud is always healthy.

### Video-only A/B — failed as a fix

The full stable-ID detector was eventually corrected and a valid PTZ video-only MPEG-TS A/B ran with AAC input still consumed but AAC removed from output mapping.

Across the analyzed deployment segment:

```text
26 valid activated PTZ video-only generations
19/26 startup-stalled with exit 74 and no first TS chunk
7/26 produced media and later stalled
0/26 remained clean through the observed generation
```

Conclusion: mapped AAC / A-V output interleave is not sufficient to explain Class A. Close the video-only line unless new evidence requires reopening it.

### Phase-6G FFmpeg probe-window A/B — also failed as a complete fix

PTZ-only wrapper experiment restored the historical Phase-6G raw input probing:

```text
video probesize=262144
video analyzeduration=500000

audio probesize=32768
audio analyzeduration=200000
```

Normal A/V mapping remained enabled. A valid activated generation reached both FFmpeg inputs, stream info, output/mapping readiness, produced MPEG-TS and `media_started=true`, then later hit exit 100 `native_header_wait`.

Conclusion: the later minimal probe windows are not the complete root cause.

### Two-stage TNP change

Later commit `1d269056...` changed the worker from the historical host-supplied sequence:

```text
4881
9029 use-count=2
768
```

to an official-current-client-inspired two-stage sequence:

```text
initial: 4881, 9029 use-count=1, 768
~5.9 s later: 9029 use-count=2, 768
```

This change was introduced after the restart/stall issue was already being investigated. It may alter behavior but cannot alone explain the original appearance of the problem.

### First post-Phase6G commit remains unisolated

The first commit after `1a561997` was:

```text
fdaeaf88694f62f770664e98d3476b69626bcda4
Expose safe runtime supervisor diagnostics in App logs
```

It changed `yi_home/run.sh` by adding a continuous Python diagnostic tail process that wakes every second and scans/reads changed `/data/runtime/*.log` files. It also changed App cleanup traps.

Although this did not alter media parsing directly, it changed process scheduling/file I/O inside the App container and was never tested as an isolated A/B. Do not assume it is behaviorally irrelevant merely because it was called diagnostics.

### Reproducibility gap

The actual `android_pppp_av_stream` worker binary is generated locally under `.analysis/.../yi-phase3g` and staged into the App. Git records the C source but not the generated runtime worker binary.

`tools/prepare_ha_app_context.py` copies the existing local runtime. Therefore checking out an older Git commit without rebuilding the worker does NOT guarantee the older worker is actually deployed.

For the baseline rollback below, the old C source must be rebuilt before staging.

The Dockerfile pins FFmpeg 6.0.1 and go2rtc by SHA, but the Home Assistant base image tag and APK-installed QEMU/Python packages are not represented by an immutable full-environment digest in the repository. If the exact source baseline still fails, investigate runtime/build/environment differences rather than continuing to search for a deterministic source commit.

## CURRENT CONTROLLED EXPERIMENT — full media-runtime source rollback

Purpose: stop changing individual FFmpeg/TNP knobs and restore the entire known-working media-runtime source boundary in one controlled experiment.

Current repository source is intentionally restored from `1a561997cdb9e9ef3561f657ae32a5c5aed28d60` for these files:

```text
tools/phase3_pppp_probe/android_pppp_av_stream.c
yi_native_av_relay.py
yi_native_av_relay_stable.py
yi_native_session_supervisor.py
yi_live_relay.py
yi_home/run.sh
```

`yi_ffmpeg_state_wrapper.py` is removed for this experiment because it did not exist at the baseline and must not alter FFmpeg execution.

This rollback intentionally removes later runtime diagnostics, graceful-supervisor changes, minimal probing, two-stage TNP startup, PTZ FFmpeg wrappers and diagnostic log tailing from the active baseline source.

The following are deliberately NOT rolled back:

- Home Assistant integration/entities;
- Phase-6G Frigate export/discovery;
- current product naming/docs around the media runtime;
- the worker rebuild/staging helper, because it is deployment tooling and is needed to make the Git-source rollback reproducible.

No timeout increase, blind retry, extra 9029, AUD injection or new media workaround is part of this experiment.

## Deployment state

At this checkpoint the baseline rollback exists in GitHub source but is NOT yet confirmed deployed to HA OS.

Critical deployment rule:

```text
pull source
 -> rebuild android_pppp_av_stream from the restored C source
 -> prepare/stage App context
 -> copy staged App context/run.sh to HA
 -> rebuild/restart local_yi_home
```

The helper:

```text
tools/phase3_pppp_probe/rebuild_phase3g_worker_and_stage_app.sh
```

rebuilds the native worker and then runs `tools/prepare_ha_app_context.py`, verifying that the staged worker SHA matches the rebuilt runtime worker.

Do not skip the worker rebuild; otherwise the current two-stage generated binary may remain in `.analysis` despite the restored C source.

## Baseline test gate after deployment

Test conditions must mirror the strongest historical gate as closely as practical:

1. PTZ stream ON.
2. All other YI App streams OFF.
3. Do not simultaneously open the official YI application during the soak.
4. Home Assistant/Frigate may consume the single App-owned RTSP stream; they are not separate PPPP sessions.
5. Target 60 minutes or stop at the first runtime recreation.
6. Primary verdict is `generation/restart_count/last_exit_code` and publication progress, not the later diagnostic log tailer (which is intentionally removed in this baseline).

PASS:

```text
60 minutes
restart_count=0
publisher attached
published bytes increasing
no exit code
```

FAIL:

Any runtime recreation/stall under this exact restored source boundary.

Interpretation:

- PASS => a source/runtime change after `1a561997` matters; perform a real forward bisect, starting with the earliest behavioral change rather than more FFmpeg knobs.
- FAIL => stop treating the problem as a simple post-`1a561997` source regression. Compare built worker SHA/runtime artifacts/base image/QEMU/PPPP environment and other state outside Git.

## Do not do next

- Do not start Phase 6E while this runtime regression is unresolved.
- Do not increase startup/stall timeouts as a fix.
- Do not add blind retries or additional 9029 requests.
- Do not reopen Frigate networking/audio/export unless there is a new regression.
- Do not inject AUD without new evidence.
- Do not judge the baseline using the now-removed FFmpeg wrapper markers.
- Do not enable multiple YI camera runtimes until the PTZ-only baseline verdict is known.
