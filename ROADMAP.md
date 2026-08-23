# YI Home Integration Roadmap

The target product architecture is documented in [`docs/product-architecture.md`](docs/product-architecture.md).
The detailed implementation sequence and exit gates are documented in [`docs/development-plan.md`](docs/development-plan.md).
Home Assistant App packaging requirements are documented in [`docs/home-assistant-app-requirements.md`](docs/home-assistant-app-requirements.md).

Latest checkpoint: [`docs/checkpoints/2026-08-23-phase6d3-haos-live-stream.md`](docs/checkpoints/2026-08-23-phase6d3-haos-live-stream.md).

## Product target

- **YI Home App/Add-on = engine/runtime**
- **YI Home Custom Integration = Home Assistant UI/devices/entities**
- **Frigate = optional media consumer**
- No Android phone, ADB, SD-card hack, manual model whitelist, UID/DID entry, per-camera YAML or manual RTSP setup in the final user experience.

## Completed phases

- Phase 1–2 — Cloud/APK/TNP research: **COMPLETE**.
- Phase 3 — Native Linux PPPP/TNP H264 + AAC media: **COMPLETE**.
- Phase 4 — Frigate interoperability: **COMPLETE**.
- Phase 5 — Multi-camera operation and scoped recovery: **COMPLETE**.
- Phase 6A — Generic account discovery by secret-safe identity: **COMPLETE**.
- Phase 6B — Generic runtime/capability cache: **COMPLETE**.
- Phase 6C — Long-running backend, lifecycle, managed go2rtc, authoritative availability and persistence: **COMPLETE**.

## Phase 6D — Home Assistant App/Add-on packaging — ACTIVE

### Phase 6D.1 — Container/runtime packaging — COMPLETE

- HA OS Local App scaffold and real amd64 image build proven.
- Persistent `/data`, protected/AppArmor operation and least-privilege networking scaffold proven.
- go2rtc 1.9.14 pinned by SHA-256.
- Bionic/native PPPP runtime staged without development credentials/state.
- Local App bootstrap proven as `local_yi_home` from `/addons/yi_home`.

### Phase 6D.2 — Configuration, storage and secrets — COMPLETE

- Authenticated Integration → App account credential handoff proven.
- `/data/yi.env` stored restrictively and atomically.
- YI password not stored in HA Config Entry.
- App bearer token persists mode `0600`.
- Account configuration/discovery survives App restart.
- Cameras are not auto-started merely because they are discovered.

### Phase 6D.3 — Networking, entities and live HA OS media — ACTIVE

Proven so far:

- Home Assistant Core consumes Supervisor/App discovery and reaches the internal backend.
- 7 camera Devices are registered.
- 3 entities per camera are live: Online, Runtime status, Stream control (21 total).
- Stream switch controls durable App runtime intent.

#### FFmpeg 8 early-stall regression — RESOLVED

The exact App image reproduced an early 20–30 second media stall with Alpine FFmpeg 8.0.1.

A/B proof:

```text
Alpine + QEMU 8.2.2 + FFmpeg 8.0.1 = FAIL around 25–30 s
Alpine + QEMU 8.2.2 + FFmpeg 6.0.1-static = PASS for 60 s
```

The App now pins FFmpeg/ffprobe 6.0.1-static with a fixed archive SHA-256. The normal App QEMU 10.1.5 remains in use.

#### One-camera HA OS long-run gate — ACTIVE / MIXED LOWER-LEVEL FAILURE MODES

HA OS continues to show runtime recreation after apparently healthy publication. The same exact pinned image passed two independent 10-minute development-host tests:

```text
Docker host networking:   generation=1, restart_count=0, 93,192,192 bytes
Docker bridge/NAT:        generation=1, restart_count=0, 81,264,640 bytes
```

Ordinary Docker bridge/NAT is therefore ruled out.

A first HA OS test with AppArmor disabled happened to pass for roughly ten minutes, but repeat testing with `apparmor: false` failed within a few minutes with `restart_count=2` and `exit=1`. Broad AppArmor A/Bs for `network,`, `signal,`, and combined `unix, + capability, + ptrace,` also failed. AppArmor is therefore **ruled out as the primary cause**; the earlier successful disabled-profile run was intermittent rather than causal.

After the first secret-safe diagnostic deployment, PTZ showed both watchdog and relay-exception generations:

```text
restart_count=1  last_exit_code=75
restart_count=3  last_exit_code=85
restart_count=4  last_exit_code=75
```

Current conclusion:

- FFmpeg 6.0.1 fixes the original FFmpeg 8 regression.
- The pinned image/runtime stack is stable for at least ten minutes under both host networking and ordinary Docker bridge/NAT outside HA OS.
- The HA OS failure is not explained by AppArmor and is not one single generic relay exit path.
- At least one generation stalls while the relay process remains alive for the 12-second watchdog window (`75`), while another reached an uncaught relay exception (`85`).
- Further HA OS security/network rule guessing is not useful.
- The next gate is **secret-safe lower-level failure observability inside the existing relay/supervisor path**.

Refined diagnostic exit codes for the next HA OS run:

```text
75 = media stall; descendant process state unavailable/startup stall
76 = media stall; qemu-aarch64 alive + ffmpeg alive
77 = media stall; qemu-aarch64 alive + ffmpeg missing
78 = media stall; qemu-aarch64 missing + ffmpeg alive
79 = media stall; qemu-aarch64 missing + ffmpeg missing
81 = native PPPP/TNP worker exited non-zero
82 = FFmpeg MPEG-TS mux exited non-zero
83 = zero video frames
84 = zero audio frames
85 = other uncaught relay exception
86 = safely unclassified relay failure
87 = relay EOFError
88 = relay RuntimeError
89 = relay subprocess TimeoutExpired
90 = relay BrokenPipeError
91 = relay OSError
92 = relay ValueError
```

The stall codes inspect only descendant process names through `/proc` immediately before watchdog termination; they do not surface PIDs, command lines or camera/runtime secrets. Exception classification uses only the exception class, never the exception message.

Next gate:

1. Keep the normal restrictive AppArmor profile and PTZ-only scope.
2. Deploy the refined diagnostic App runtime.
3. Run until the first one or two recreations rather than waiting for a long-duration pass.
4. Follow the specific lower-level stage reported by `last_exit_code`.
5. Only after one-camera long-run stability is proven should two-camera HA OS testing resume.

### Phase 6D.4 — Architecture support — PLANNED

- Initial target remains `amd64` only.
- Advertise `aarch64` only after independent full native/QEMU proof.

Phase 6D exit gate remains:

- fresh HA OS App install/start;
- Integration-driven account setup;
- automatic camera/device/entity discovery;
- long-running stable App-owned media under the final restrictive security profile;
- at least two simultaneous independent streams;
- persisted desired-running behavior survives App restart;
- no terminal/manual UID/DID/model/RTSP/YAML/Android dependency in normal use.

## Phase 6E — Home Assistant Custom Integration — ACTIVE

Foundation already live:

- Hass.io/Supervisor discovery Config Flow;
- account form and authenticated handoff;
- Config Entry without YI password;
- coordinator-driven camera inventory/status;
- 7 Devices / 21 Online, Runtime and Stream entities.

Remaining:

- camera/live-view entity backed by the App-owned media path;
- polished translations/diagnostics and reauthentication UX;
- dynamic camera additions where practical;
- final secret-redaction tests.

## Phase 6F — Zero-manual-config onboarding — PLANNED

```text
Install YI Home App
 -> Add YI Home Integration
 -> enter YI account details / region
 -> Found N cameras
 -> Finish
```

No UID/DID/model/TNP/RTSP/YAML required from the user.

## Phase 6G — Frigate integration/export — PLANNED

- Stable App-owned RTSP endpoints.
- Frigate remains optional and separate from the core App/Integration lifecycle.
- Validate Frigate only after the App-native long-run and multi-camera gates pass.

## Later work

- Real timestamp/timebase cleanup.
- Additional TNP profiles/model coverage.
- PTZ/camera controls where generic/safe.
- Motion/event integration.
- Reduce/eliminate QEMU where practical.
- Packaging/release automation and HACS/App repository distribution.
