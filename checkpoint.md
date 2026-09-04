# YI Camera Connect / YI RTSP — Project Checkpoint

_Last updated: 2026-09-04_
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

## zforce native-record probe — DEPLOYED AND COLLECTED

Source state:

- `yi_native_av_relay.py` logs only the first three secret-safe native media
  records per channel: YAV1 framing, TNP header fields, codec/flags,
  sequence/delta, timestamp/delta, dimensions and loss counters;
- video records also log frame type, Annex-B framing and NAL types without
  logging payload bytes;
- `yi_runtime_lifecycle.py` forwards only those exact fixed probe prefixes
  from the per-camera runtime log after a generation exits;
- focused tests cover metadata accuracy, wrap-safe deltas and the allow-listed
  log bridge;
- App version advanced from `0.1.0` to `0.1.1` so the Supervisor cannot retain
  a stale same-version image;
- the John Van Sickle URL currently serves a 7 KB JavaScript challenge instead
  of the archive. `yi_home/Dockerfile` now uses the frc971 archive mirror; the
  downloaded mirror artifact matched the original pinned SHA-256 exactly:
  `28268bf402f1083833ea269331587f60a242848880073be8016501d864bd07a5`.

Deployment state:

- deployed source SHA-256 values match the repository working tree:
  `yi_native_av_relay.py=644dc013...cb17`,
  `yi_runtime_lifecycle.py=40cfbc0f...484c`,
  `Dockerfile=7c41f197...7cb2`, and `config.yaml=f6050029...1681`;
- backups are under `/config/.codex-backups/yi-home-native-probe-20260903`
  and `/config/.codex-backups/yi-home-version-20260904`;
- `/addons/yi_home.pre_baseline` duplicated `slug: yi_home` with stale source.
  Its `config.yaml` was reversibly renamed to `config.yaml.disabled` so only
  `/addons/yi_home` is registered;
- Supervisor was restarted to rescan the local App, then update/install built
  and started `local_yi_home` version `0.1.1` successfully;
- live final state: zforce OFF/stopped as intended; pool and PTZ ON/running,
  both publisher-attached with restart count 0 after the App update.

Evidence:

```text
focused new tests: PASS (2/2)
Python compile: PASS
broader focused modules: 6 PASS, 1 known Windows POSIX-mode assertion failure
App version/state: 0.1.1 / started / update_available=false

zforce controlled 0.1.1 generation:
restart_count=0
publisher_attached=true
published_bytes before stop=7,247,400

channel 3 P-video:
sequence 2 -> 3 -> 4 (delta 1)
timestamp_ms deltas 36 ms, 51 ms
Annex-B NAL type 1

channel 1 AAC audio:
sequence 1 -> 2 -> 3 (delta 1)
timestamp_ms deltas 61 ms, 71 ms

channel 2 I-video:
sequence 1 -> 41 -> 81 (delta 40)
timestamp deltas 2 s; timestamp_ms deltas 2003 ms
Annex-B NAL types 7,8,5 (SPS/PPS/IDR)

all sampled records:
TNP version 2; codec video=78/audio=138; 2304x1296;
out_loss=0; in_loss=0; payload_logged=false
```

The final user-requested stop ended the child generation with exit 81 after it
had already published successfully; treat this as stop-path evidence, not a
spontaneous stability failure.

Conclusion:

- zforce's initial native YAV1/TNP framing, sequence progression and timestamps
  are coherent; the historical restart loop is not explained by malformed
  initial headers, sequence jumps or timestamp corruption;
- the next investigation boundary remains the long-running worker/QEMU read
  path and FFmpeg pipe/backpressure stages after successful startup.

Next step:

1. keep zforce OFF and pool/PTZ ON;
2. for the next zforce soak, correlate the last safe stage and worker record
   totals at each spontaneous exit rather than adding more header parsing;
3. fix the stop path separately if exit 81 on an explicit OFF action needs to
   be normalized to a clean administrative exit.

## Credential replacement UI — DEPLOYED, UI CAPABILITY VERIFIED

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

- commit `dc49c3f` is pushed to `phase-3-linux-pppp`;
- `config_flow.py`, `strings.json` and `translations/he.json` were copied to
  `/config/custom_components/yi_home` on HA OS;
- the previous three files are backed up under
  `/config/.codex-backups/yi_home-dc49c3f`;
- Home Assistant configuration validation passed and Core restarted cleanly;
- the live Config Entry is loaded and reports `supports_reconfigure=true`;
- no YI account or password was submitted during deployment, so recovery of
  camera discovery is still pending the user's UI submission.

Evidence:

```text
config_flow Python compile: PASS
English/Hebrew translation JSON parse: PASS
Integration smoke gates through account-update translations and secret scan: PASS
Windows tar bundle: PASS (45,592 bytes)
bundle SHA-256: 2440b42243db3bf58123574dec0ba91a4de51b8b9f2a816f0e11320e7a3ddff0
HA configuration check before restart: PASS
live Integration state after restart: loaded
live Integration supports_reconfigure: true
deployed source checksums match commit dc49c3f: PASS
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

1. use **Settings -> Devices & services -> YI Home -> Reconfigure** to submit
   the current YI account and password;
2. confirm the App reports `account_configured=true` and successful discovery;
3. verify camera entities recover from `unavailable` without reinstalling the
   App or Integration.

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
