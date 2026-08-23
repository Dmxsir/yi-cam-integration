# Checkpoint — 2026-08-23 — Phase 6D.3 HA OS live-stream investigation

## Status

- Phase 6D.1 App/container packaging: **COMPLETE**.
- HA OS Local App bootstrap: **COMPLETE**.
- Phase 6D.2 Integration → App account credential handoff and restart persistence: **COMPLETE**.
- Home Assistant device/entity registration: **PASS** — 7 cameras, 3 entities per camera (21 entities total).
- Phase 6D.3 short-run one-camera HA OS media: **PASS**.
- Exact pinned image 10-minute host-network long-run on development host: **PASS**.
- Exact pinned image 10-minute Docker bridge/NAT long-run on development host: **PASS**.
- HA OS one-camera long-run: **FAIL / ACTIVE INVESTIGATION**.
- Multi-camera HA OS gate: **BLOCKED**.

## Proven media/runtime baseline

The App remains pinned to FFmpeg/ffprobe 6.0.1-static and QEMU 10.1.5. The earlier Alpine FFmpeg 8.0.1 20–30 second stall was independently reproduced and fixed by the FFmpeg pin.

The exact pinned image subsequently passed two 600-second development-host runs using the full persistent backend/lifecycle/native relay/shared-go2rtc path and no RTSP consumer:

```text
Docker host networking:
  generation=1
  restart_count=0
  last_exit_code=null
  published_bytes=93192192

Docker bridge/NAT:
  generation=1
  restart_count=0
  last_exit_code=null
  published_bytes=81264640
```

The bridge run also showed continuous PPPP/TNP authentication and MPEG-TS progress. Ordinary Docker bridge/NAT is therefore ruled out.

## HA OS failure evidence

On HA OS the PTZ runtime repeatedly recreates after apparently healthy publication. Both watchdog stalls and relay failures have been observed. `published_bytes` is generation-local and resets on recreation; current-generation `publisher_attached=true` does not explain the previous generation's exit.

Historical outcomes included:

```text
exit=75  # media-stall supervisor watchdog
exit=1   # legacy generic relay/native/mux failure path
```

After secret-safe diagnostic deployment, the observed sequence included:

```text
restart_count=1  last_exit_code=75  published_bytes(current generation)=14483456
restart_count=3  last_exit_code=85  published_bytes(current generation)=8388608
restart_count=4  last_exit_code=75  published_bytes(current generation)=7208960
```

This is important: the HA OS instability is **not one single generic exit path**. At least two observable failure modes are occurring:

- the relay process remains alive but stops forwarding MPEG-TS for the 12-second watchdog window (`75`);
- another generation reaches an uncaught relay exception (`85`).

The two may still share one lower-level cause, so the next diagnostics are designed to distinguish QEMU/native-worker vs FFmpeg/mux vs relay parser/cleanup behavior without exposing raw runtime material.

## AppArmor investigation — ruled out as primary cause

A first HA OS run with AppArmor disabled remained stable for roughly ten minutes, which initially made the AppArmor policy a strong suspect. That correlation did not survive repeat testing.

Controlled follow-up tests with AppArmor enforcing still failed after broadening these policy classes independently:

```text
network,
signal,
unix, + capability, + ptrace,
```

A complain-flag experiment also continued to recreate with `exit=1`, and the available HA OS shell/log surfaces did not expose useful YI-specific audit events.

Most decisively, a repeat run with the App configured with:

```text
apparmor: false
```

also failed within a few minutes:

```text
State: running
Desired: True
Process: True
Restarts: 2
Reason: recreated_after_exit
Exit: 1
Publisher: True
Bytes: 12517376
Error: None
```

Therefore AppArmor is **not the root cause** of the long-run HA OS failure. The earlier AppArmor-disabled pass was an intermittent successful run, not a causal fix. The product should remain on the normal restrictive AppArmor profile; no broad policy relaxation is justified.

## Observability gap

The Home Assistant Runtime status sensor exposes the supervised process exit code, while the detailed per-camera runtime log lives inside App `/data/runtime` and is not directly visible from the normal Terminal & SSH App.

The relay already emits secret-safe terminal markers such as:

```text
native_worker_exit=<rc>; mpegts_mux_exit=<rc>; video_frames=<n>; audio_frames=<n>
PHASE3G_NATIVE_AV=FAIL
```

Continuing environment A/B tests without converting these safe markers into visible structured status would be guesswork.

## Secret-safe failure-stage diagnostics

The stable-id relay adapter converts existing fixed-format relay outcomes into diagnostic process exit codes. It never exposes exception messages, raw log lines, camera credentials, UID/DID, PPPP key material or connection material.

Existing relay-summary codes:

```text
81 = native PPPP/TNP worker exited non-zero
82 = FFmpeg MPEG-TS mux exited non-zero
83 = relay ended with zero video frames
84 = relay ended with zero audio frames
85 = generic uncaught relay exception (legacy diagnostic generation)
86 = relay failure could not be classified safely
```

The latest refinement classifies uncaught exception **types** without surfacing exception messages:

```text
87 = relay EOFError
88 = relay RuntimeError
89 = relay subprocess TimeoutExpired
90 = relay BrokenPipeError
91 = relay OSError
92 = relay ValueError
85 = other uncaught relay exception
```

The session supervisor now also performs a best-effort `/proc` descendant snapshot at a **post-start media stall**, before terminating the relay process group. Only the presence/absence of `qemu-aarch64` and `ffmpeg` is encoded; no PID or command line is surfaced:

```text
75 = media stall; process state unavailable (also retained for startup stall)
76 = media stall; qemu-aarch64 alive, ffmpeg alive
77 = media stall; qemu-aarch64 alive, ffmpeg missing
78 = media stall; qemu-aarch64 missing, ffmpeg alive
79 = media stall; qemu-aarch64 missing, ffmpeg missing
```

This should answer two high-value questions from the next failing generations:

1. For watchdog stalls, were QEMU/native worker and FFmpeg still alive when MPEG-TS stopped moving?
2. For relay exceptions, what safe exception class escaped the proven relay path?

The HA Runtime sensor mapping in the repository has corresponding `last_failure_stage` labels once the updated custom integration is deployed.

Relevant diagnostic commits in this investigation include:

```text
08ef6609  Add secret-safe relay failure exit diagnostics
c7c49997  Expose secret-safe YI runtime failure stage
fd57152d  Test secret-safe relay failure classification
3c3ca5dd  Refine relay exception diagnostics
498fbd7c  Classify media stalls by child process state
b4cfa831  Expose refined HA runtime failure stages
eb00d4ad  Test refined relay exception diagnostics
1c151fe0  Test media-stall process diagnostics
```

## Next gate

1. Keep the normal App security configuration (`apparmor: true`) and PTZ-only test scope.
2. Stage/rebuild the App with the latest refined diagnostic relay and supervisor.
3. Run PTZ until the first one or two recreations; do not wait for a long-duration pass.
4. Record `last_exit_code`.
5. Follow the resulting lower-level stage rather than changing HA OS security/network settings.

Interpretation of the next useful exits:

- `76`: both QEMU/native worker and FFmpeg were still alive while MPEG-TS stalled; investigate pipe/read/write deadlock or source starvation.
- `77`: QEMU/native worker alive but FFmpeg disappeared; focus on mux lifetime/failure.
- `78`: FFmpeg alive but QEMU/native worker disappeared; focus on native worker/PPPP termination and relay blocking behavior.
- `79`: both descendants disappeared while the Python relay remained alive; focus on relay cleanup/wait behavior.
- `87`: native worker/media pipe likely reached EOF; correlate with worker termination path.
- `88`: relay validation/runtime invariant failure; add a safe sub-stage only if needed.
- `89`: cleanup/wait timeout; focus on child/mux shutdown lifecycle.
- `90`/`91`: pipe or OS I/O failure; identify which safe operation needs sub-stage instrumentation.
- `92`: parser/value invariant failure; add a safe parser stage if needed.
- `81`/`82`: direct native-worker or FFmpeg non-zero termination.

Do not resume the two-camera gate until one-camera HA OS long-run stability is proven.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString, raw connection material, raw per-camera runtime logs, exception messages or process command lines.
