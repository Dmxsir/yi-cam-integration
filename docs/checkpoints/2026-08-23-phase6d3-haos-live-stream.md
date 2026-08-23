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

On HA OS the PTZ runtime repeatedly recreates after apparently healthy publication. `published_bytes` is generation-local and resets on recreation; current-generation `publisher_attached=true` does not explain the previous generation's exit.

Historical outcomes included generic `exit=1`, watchdog `exit=75`, and later structured diagnostics. A useful sequence from the refined deployment was:

```text
restart_count=1  last_exit_code=75
restart_count=3  last_exit_code=85
restart_count=4  last_exit_code=75
```

After exception-type refinement, one generation produced:

```text
restart_count=1  last_exit_code=88
```

`88` identified an uncaught relay `RuntimeError`. A further safe sub-stage classifier then identified the actual RuntimeError family as:

```text
restart_count=1  last_exit_code=95
```

`95` means **audio/AAC unit validation failure** inside the live relay. This narrowed one failure path to malformed/corrupt channel-1 audio records rather than AppArmor, Docker networking, FFmpeg startup, or a generic process exit.

## AAC recovery fix

The native worker already frames each media record atomically before writing it to the Python relay. One malformed channel-1 audio unit therefore should not tear down an otherwise healthy H.264 session.

`yi_native_av_relay.py` now raises `AudioUnitValidationError` only for packet-level audio validation failures such as malformed TNP audio structure, unexpected AAC codec, invalid/decrypted ADTS framing, or invalid ADTS sample-rate index. The continuous live loop drops only that isolated audio record and continues. Session/config invariants such as a bad AES key length remain fatal.

Safe logs expose only a count:

```text
audio_validation_drop_count=<n>; action=drop_and_continue
```

No raw audio bytes, credentials or exception text are exposed.

Relevant commits:

```text
58cdef37  Tolerate isolated malformed AAC units in live relay
4effefa7  Test recoverable malformed AAC unit handling
```

After this fix was deployed, the next observed restart was **not `95`**. It was `75`, which confirms that at least one separate post-start stall path remains.

## AppArmor investigation — ruled out as primary cause

A first HA OS run with AppArmor disabled remained stable for roughly ten minutes, which initially made the AppArmor policy a strong suspect. That correlation did not survive repeat testing.

Controlled follow-up tests with AppArmor enforcing still failed after broadening these policy classes independently:

```text
network,
signal,
unix, + capability, + ptrace,
```

A complain-flag experiment also continued to recreate with `exit=1`, and the available HA OS shell/log surfaces did not expose useful YI-specific audit events.

Most decisively, a repeat run with `apparmor: false` also failed within a few minutes with `restart_count=2` and `exit=1`.

Therefore AppArmor is **not the root cause**. The product remains on the normal restrictive AppArmor profile; no broad policy relaxation is justified.

## Structured failure-stage diagnostics

The stable-id relay adapter maps only fixed, secret-safe failure classes to process exit codes. It does not expose exception messages, raw log lines, camera credentials, UID/DID, PPPP key material or connection material.

Current codes:

```text
74 = startup stall before first MPEG-TS bytes
75 = post-start media stall; child process state unavailable
76 = post-start stall; qemu-aarch64 alive, ffmpeg alive
77 = post-start stall; qemu-aarch64 alive, ffmpeg missing
78 = post-start stall; qemu-aarch64 missing, ffmpeg alive
79 = post-start stall; qemu-aarch64 missing, ffmpeg missing
81 = native PPPP/TNP worker exited non-zero
82 = FFmpeg MPEG-TS mux exited non-zero
83 = zero video frames
84 = zero audio frames
85 = other uncaught relay exception
86 = safely unclassified relay failure
87 = relay EOFError
88 = relay RuntimeError not otherwise classified
89 = relay subprocess TimeoutExpired
90 = relay BrokenPipeError
91 = relay OSError
92 = relay ValueError
93 = native stream header/framing RuntimeError
94 = invalid native media record RuntimeError
95 = audio unit validation RuntimeError family
96 = AAC format changed during live session
97 = H.264/video unit validation RuntimeError
98 = native worker pipe setup RuntimeError
```

The startup/media distinction is now explicit: after deploying the `74` split, another PTZ run still returned `75`. That proves the failure occurred **after media had started**, not during startup.

## Why `75` remained ambiguous on HA OS

The first stall classifier attempted to inspect:

```text
/proc/<relay-pid>/task/<relay-pid>/children
```

On HA OS this returned unavailable at the stall point, so the supervisor could not convert `75` into `76–79` even though the relay itself directly owns the QEMU and FFmpeg `Popen` handles.

Continuing to depend on `/proc` would therefore leave the most important stall branch ambiguous.

## Relay-owned child-state marker

The next diagnostic no longer depends on `/proc` as the primary source.

`yi_native_av_relay.py` now runs a lightweight daemon reporter that polls only its own direct process handles and atomically writes a `0600` marker containing exactly two booleans:

```text
qemu_alive=0|1
ffmpeg_alive=0|1
```

The outer session supervisor creates a unique marker path under `/tmp`, passes it via `YI_PHASE3_CHILD_STATE_MARKER`, and reads that marker when a post-start stall fires. `/proc` remains only a development fallback.

The marker contains no PID, command line, camera identity, credentials, token, UID/DID, PPPP material, media bytes or exception text.

Relevant commits:

```text
2c669521  Use relay-owned child state for stall diagnostics
873b29e7  Report secret-safe relay child liveness
4eead17a  Test relay-owned stall state markers
4a0712e5  Test secret-safe relay child state marker
```

## Next gate

1. Keep `apparmor: true` and PTZ-only scope.
2. Deploy the latest `yi_native_session_supervisor.py` and `yi_native_av_relay.py` together.
3. Run PTZ until the first recreation; no long wait is required.
4. Record `last_exit_code`.
5. Follow the resulting branch:

```text
76 -> QEMU/native worker and FFmpeg both alive: investigate source starvation / pipe / mux deadlock
77 -> QEMU alive, FFmpeg missing: focus on FFmpeg mux termination
78 -> QEMU missing, FFmpeg alive: focus on native worker / PPPP session termination
79 -> both missing while relay survives: focus on relay child cleanup/lifecycle
74 -> startup/session establishment issue
95 -> isolated AAC handling still not sufficient; inspect remaining audio invariant
other structured code -> follow that exact stage
```

Do not resume the two-camera gate until one-camera HA OS long-run stability is proven.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString, raw connection material, raw per-camera runtime logs, exception messages, process command lines or PIDs.
