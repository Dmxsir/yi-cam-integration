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

On HA OS the PTZ runtime repeatedly recreates after apparently healthy publication. Both outcomes have been observed:

```text
exit=75  # media-stall supervisor watchdog
exit=1   # relay/native/mux generic failure path
```

`published_bytes` is generation-local and resets on recreation. `publisher_error=null` on the current generation does not explain a previous generation's relay exit.

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

Therefore AppArmor is **not the root cause** of the long-run HA OS failure. The earlier AppArmor-disabled pass was an intermittent successful run, not a causal fix. The product should return to the normal restrictive AppArmor profile; no broad policy relaxation is justified.

## Observability gap

The current Home Assistant Runtime status sensor exposes only the generic supervised process exit code. For `exit=1`, the detailed per-camera runtime log inside App `/data/runtime` can distinguish several lower-level outcomes, but that file is not directly visible from the normal Terminal & SSH App.

The relay already emits secret-safe terminal markers such as:

```text
native_worker_exit=<rc>; mpegts_mux_exit=<rc>; video_frames=<n>; audio_frames=<n>
PHASE3G_NATIVE_AV=FAIL
```

Continuing environment A/B tests without surfacing these markers would be guesswork.

## Secret-safe failure-stage diagnostics added

`yi_native_av_relay_stable.py` now captures only the existing fixed-format, secret-safe relay summary and maps generic relay failure to distinct diagnostic exit codes. No raw log lines, camera credentials, UID/DID, PPPP key material or exception messages are surfaced.

Diagnostic codes:

```text
75 = supervisor media stall
81 = native PPPP/TNP worker exited non-zero
82 = FFmpeg MPEG-TS mux exited non-zero
83 = relay ended with zero video frames
84 = relay ended with zero audio frames
85 = unhandled relay exception (exception message suppressed)
86 = relay failure could not be classified safely
```

The HA Runtime sensor also has a `last_failure_stage` mapping for these codes once the updated custom integration is deployed.

Relevant commits:

```text
08ef6609  Add secret-safe relay failure exit diagnostics
c7c49997  Expose secret-safe YI runtime failure stage
fd57152d  Test secret-safe relay failure classification
```

## Next gate

1. Restore the normal App source (`apparmor: true` and the repository AppArmor profile).
2. Deploy the newly staged App runtime containing the diagnostic stable relay adapter.
3. Run **PTZ only** until the first recreation.
4. Record the new `last_exit_code` (and `last_failure_stage` if the Integration mapping is deployed).
5. Follow the resulting lower-level stage instead of changing more HA OS security/network settings.

Interpretation:

- `81`: investigate native worker/PPPP session termination.
- `82`: investigate FFmpeg MPEG-TS mux lifetime/pipe behavior on HA OS.
- `83`/`84`: investigate media-frame starvation/type-specific parsing.
- `85`: add a second secret-safe exception-stage marker around the identified relay section.
- `86`: extend structured diagnostics only as needed; do not expose raw logs.
- `75`: focus on why an otherwise-live relay stops forwarding bytes for the 12-second watchdog window.

Do not resume the two-camera gate until one-camera HA OS long-run stability is proven.

## Security

This checkpoint contains no YI password, camera password, cloud/session token, App bearer token, UID/DID, PPPP InitString, raw connection material or raw per-camera runtime logs.
