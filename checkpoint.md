# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-09-03_
_Branch: `phase-3-linux-pppp`  
_Repository: `Dmxsir/yi-cam-integration`

## Purpose

Canonical handoff/context for the YI camera reverse-engineering / Home Assistant project.

**Mandatory workflow:** every repository source change must update this checkpoint with source state, deployment state, evidence, conclusions and next step.

## User workflow constraint

1. Assistant edits GitHub directly.
2. User gets at most one laptop command at a time.
3. User gets at most one Home Assistant command at a time.
4. Do not ask the user to edit/commit/push source locally when GitHub can be updated directly.
5. Do not send the next command until the previous result is reported.

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
 -> Home Assistant / external Frigate
```

The App owns the PPPP/TNP session. Home Assistant and Frigate consume the App-owned RTSP stream and do not create independent YI sessions.

## Credential replacement UI — SOURCE COMPLETE, DEPLOYMENT PENDING

Source state:

- the existing YI Home Config Entry now exposes Home Assistant's standard
  **Reconfigure** flow;
- the same secret-safe account form is available for a future automatic
  reauthentication trigger;
- replacement credentials are validated and persisted by the App's existing
  authenticated `/api/v1/account` endpoint;
- the password and account remain absent from the Home Assistant Config Entry;
- English and Hebrew UI strings and the Integration smoke gate cover both
  account-update steps.

Deployment state:

- not yet copied to `/config/custom_components/yi_home` on HA OS;
- the running Integration therefore still reports no reconfigure support.

Evidence:

```text
config_flow Python compile: PASS
English/Hebrew translation JSON parse: PASS
Integration smoke gates through account-update translations and secret scan: PASS
Windows tar bundle: PASS (45,592 bytes)
bundle SHA-256: 2440b42243db3bf58123574dec0ba91a4de51b8b9f2a816f0e11320e7a3ddff0
```

The broad Python suite was also sampled: unrelated existing failures remain on
Windows because several tests require POSIX file modes and APK feature assets.
No failure touched the Integration account-update source.

Conclusion:

- changing a YI cloud password no longer requires reinstalling the App or
  deleting the Integration once this Integration source is deployed;
- automatic presentation of the reauthentication dialog still depends on the
  App exposing a secret-safe `reauth_required` state.

Next step:

1. commit and push this source on `phase-3-linux-pppp`;
2. deploy `custom_components/yi_home` to HA OS and restart Home Assistant;
3. confirm the live entry reports reconfigure support;
4. use the UI form to submit the current YI account/password and verify camera
   discovery recovers.

## Phase 6G

Phase 6G Frigate integration/export is COMPLETE. Do not reopen it absent a real regression.

Validated: live video/audio, detection, recording, stream OFF/ON lifecycle, dynamic Supervisor RTSP host-port discovery and secret-safe Frigate export.

PTZ identity:

```text
stable_id = e2f22804fecdbd8c3561
stream_id = yi_e2f22804fecd
RTSP path = /yi_e2f22804fecd
```

Do not confuse the 20-character stable ID with the 12-character public/log prefix.

## Strong historical HA OS baseline

Commit:

```text
9c554a1655a058669d1844a8e353b7f27b6d4af5
Advance HA OS media gates after async writer pass
```

Recorded PTZ-only result on HA OS:

```text
60 minutes
restart_count=0
no last exit code
publisher remained attached
published bytes increased continuously
```

Later Phase-6G completion commit:

```text
1a561997cdb9e9ef3561f657ae32a5c5aed28d60
Mark Phase 6G Frigate integration complete
```

used the same media-runtime source as the 60-minute gate. Changes from `9c554a16` to `1a561997` were HA/Frigate/UI/export work, not media-runtime changes.

There is no historical five-camera 60-minute HA OS soak. Historical evidence is PTZ-only 60-minute PASS plus a two-camera smoke PASS.

## Regression evidence — 2026-08-26

### Multi-camera load is not required

With every YI stream OFF except PTZ, PTZ still failed. A representative sequence on the pre-rollback build was:

```text
exit 100 native_header_wait after sustained publication
next generation worker 60
next valid generation startup stall 74
next generation worker 40
later generation media_started=true
```

Therefore concurrency may affect frequency, but is not a necessary condition.

### Official YI app check

The official app briefly failed while our direct PPPP session was also active; this is not proof of an upstream outage because two direct clients may contend for the live session.

When the custom PTZ stream was OFF, the official app streamed correctly. No long official-app-only soak was performed.

### Video-only A/B — failed

Valid full-stable-ID PTZ A/B:

```text
26 activated generations
19 startup-stalled with exit 74/no first TS
7 produced media and later stalled
0 remained clean through the observed generation
```

Mapped AAC / A-V output interleave is not sufficient to explain the failure.

### Phase-6G FFmpeg probe A/B — failed as complete fix

Restoring historical live input probes for PTZ:

```text
video probesize=262144 analyzeduration=500000
audio probesize=32768 analyzeduration=200000
```

still allowed a valid generation to publish and later fail with exit 100 `native_header_wait`.

### Later two-stage TNP startup is not the original cause

The later worker change introduced the official-current-client-inspired second START_REALTIME/AUDIO around 5.9 seconds. It was added after the issue was already under investigation and cannot by itself explain the original onset.

## Full Phase-6G media-source rollback — DEPLOYED AND FAILED

Rollback commit:

```text
90f76ffdc503bb752debbaf4d97797bdb57bac6e
Restore Phase 6G media runtime baseline
```

Restored from `1a561997` as one controlled bundle:

```text
tools/phase3_pppp_probe/android_pppp_av_stream.c
yi_native_av_relay.py
yi_native_av_relay_stable.py
yi_native_session_supervisor.py
yi_live_relay.py
yi_home/run.sh
```

and removed the later `yi_ffmpeg_state_wrapper.py`.

The native worker was rebuilt from the restored C source before staging. Deployed/staged SHA-256 matched:

```text
e91dacc2182bf8371bfb19bf4a6063ead3a6560f5dcc898c8430f0e773f5f200
```

PTZ-only test after rebuild/restart initially had live feed in HA and Frigate, then failed within roughly two minutes:

```text
desired_running=true
process_alive=true
restart_count=1
last_reason=recreated_after_exit
last_exit_code=100
last_failure_stage=media_stall_native_header_wait
publisher_attached=false
published_bytes=0
```

Verdict: restoring the known-good Git media-source boundary did **not** restore stability. Stop treating this as a simple deterministic source regression after `1a561997`.

Important limitation: the historical native worker binary hash was not recorded, so rebuilding old C source today does not prove bit-identical native code to the historical 60-minute run.

## Runtime/environment reproducibility gap

The App is a local build (`ha apps info`: `build: true`, `repository: local`). Rebuilding today creates a new image from the current base/tag/package repositories.

`yi_home/Dockerfile` pins FFmpeg 6.0.1 and go2rtc by version + SHA, but uses:

```dockerfile
FROM ghcr.io/home-assistant/base:3.23
RUN apk add --no-cache ca-certificates curl py3-cryptography python3 qemu-aarch64 xz
```

The base image is a mutable tag rather than an immutable digest, and QEMU/Python/cryptography APK versions are not pinned. Therefore old Git source + current rebuild is not a bit-identical historical runtime environment.

The generated `android_pppp_av_stream` binary is also not tracked in Git; `prepare_ha_app_context.py` stages a locally generated artifact.

These are now primary investigation targets.

## CURRENT CONTROLLED EXPERIMENT — one-shot environment fingerprint

Source change after the failed baseline rollback: `yi_home/run.sh` now logs a single secret-safe environment line **before** the backend starts:

```text
Runtime versions: qemu=<qemu-aarch64 --version first line>;
python=<python3 --version>;
qemu_package=<apk package version>;
python_package=<apk package version>;
cryptography_package=<apk package version>;
secrets_exposed=false
```

This diagnostic:

- runs once at App startup;
- starts no resident process;
- does not scan runtime logs;
- does not change PPPP/TNP, worker, relay, FFmpeg or go2rtc code;
- exists only to fingerprint mutable base-image/APK runtime components.

All media-runtime source remains at the Phase-6G baseline restored by `90f76ff...`; only this one-shot `run.sh` diagnostic differs.

## Next deployment/test step

1. Pull this commit to the laptop.
2. Copy the updated `yi_home/run.sh` to `/addons/yi_home/run.sh`.
3. Rebuild/restart `local_yi_home` once.
4. Read the App startup log and record the `Runtime versions:` line.

No native worker rebuild is required for this diagnostic-only `run.sh` change because the already staged worker SHA remains `e91dacc2...f200`.

After collecting versions, compare them against what can be reconstructed from historical HA base/QEMU package state before adding any new media knobs.

## Exit-code reminders

```text
40  native PPPP_Connect negative
50  initial native PPPP_Write failure
60  first channel-0 PPPP_Read failure/not exactly 8 bytes
74  startup stall: no MPEG-TS within 45 s
81  native worker failure propagated by stable wrapper
100 media stall: native_header_wait
101 media stall: native_payload_wait
102 audio_pipe_write
103 video_pipe_write
104 mux_starting
105 relay_processing
```

Do not infer semantics for raw PPPP negatives such as `-3003` without evidence.

## Do not do next

- Do not start Phase 6E.
- Do not increase startup/stall timeouts.
- Do not add blind retries or extra 9029 requests.
- Do not inject AUD without new evidence.
- Do not reopen solved Frigate networking/audio/export absent regression.
- Do not enable multiple YI runtimes until the PTZ-only root cause is understood.
- Do not claim the old worker binary is bit-identical; its historical hash is missing.
- Do not treat the one-shot environment diagnostic as a media-path fix.
