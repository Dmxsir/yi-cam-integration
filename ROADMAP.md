# YI Home Integration Roadmap

The target product architecture is documented in [`docs/product-architecture.md`](docs/product-architecture.md).
The detailed implementation sequence and exit gates are documented in [`docs/development-plan.md`](docs/development-plan.md).
Home Assistant App packaging requirements are documented in [`docs/home-assistant-app-requirements.md`](docs/home-assistant-app-requirements.md).

Latest checkpoint: [`docs/checkpoints/2026-08-24-phase6g-supervisor-port-discovery-pass.md`](docs/checkpoints/2026-08-24-phase6g-supervisor-port-discovery-pass.md).

## Product target

- **YI RTSP App = engine/runtime**
- **YI Camera Connect = Home Assistant UI/devices/entities**
- **Frigate = optional media consumer**
- No Android phone, ADB, SD-card hack, manual model whitelist, UID/DID entry, per-camera YAML or manual RTSP setup in the final Home Assistant user experience.

Current internal `yi_home` identifiers remain unchanged until the explicit compatibility-sensitive rename/repository-split migration.

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
- Online, Runtime status and Stream control entities are live for each camera.
- Stream switch controls durable App runtime intent.
- One-camera HA OS long-run with independent live FFmpeg input writers: **PASS — 60 minutes, restart_count=0**.
- Two-camera simultaneous HA OS smoke gate: **PASS — both runtimes remained healthy with restart_count=0 and no exit codes during the accepted test window**.

#### FFmpeg 8 early-stall regression — RESOLVED

The exact App image reproduced an early 20–30 second media stall with Alpine FFmpeg 8.0.1.

A/B proof:

```text
Alpine + QEMU 8.2.2 + FFmpeg 8.0.1 = FAIL around 25–30 s
Alpine + QEMU 8.2.2 + FFmpeg 6.0.1-static = PASS for 60 s
```

The App now pins FFmpeg/ffprobe 6.0.1-static with a fixed archive SHA-256. The normal App QEMU 10.1.5 remains in use.

#### One-camera HA OS long-run gate — PASS

Earlier HA OS runs recreated after apparently healthy publication while the same exact pinned image passed independent 10-minute host-network and bridge/NAT tests. AppArmor, ordinary Docker NAT and the original FFmpeg 8 regression were ruled out.

Structured diagnostics isolated two lower-level paths:

```text
95 = malformed/corrupt AAC unit validation
103 = qemu + ffmpeg alive; relay blocked writing H.264 into FFmpeg
```

The `95` path was made recoverable by dropping only isolated malformed AAC units. The remaining repeated `103` path was traced to the single-thread relay feeding both FFmpeg inputs. A blocked H.264 pipe could stop the same thread from feeding AAC and consuming native media.

The live adapter now decouples FFmpeg inputs:

```text
native relay main loop
  -> video queue -> dedicated H.264 writer -> FFmpeg video pipe
  -> audio queue -> dedicated AAC writer  -> FFmpeg audio pipe
```

Result on HA OS under the normal restrictive AppArmor profile:

```text
PTZ-only long-run: 60 minutes
restart_count=0
last_reason=started
no last exit code
publisher remained attached
published bytes continued increasing
```

This is a strong A/B against the previous run that accumulated 48 `103` restarts in roughly one hour.

Relevant commits:

```text
58cdef37  Tolerate isolated malformed AAC units in live relay
dee48d80  Decouple live FFmpeg video and audio pipe writers
e7e3e2af  Test independent live FFmpeg input writers
7cd583fb  Record persistent video pipe stalls and async writer fix
```

#### Multi-camera HA OS gate — IN PROGRESS / SMOKE PASS

After the one-camera long-run PASS, two cameras were enabled concurrently. During the accepted smoke window both reported healthy runtime state, `restart_count=0`, and no exit code. The user explicitly accepted moving forward without another one-hour hold.

This removes the previous hard blocker on continuing Phase 6E work, while longer multi-camera soak testing can still be repeated later as a regression gate before release.

### Phase 6D.4 — Architecture support — PLANNED

- Initial target remains `amd64` only.
- Advertise `aarch64` only after independent full native/QEMU proof.

Phase 6D exit gate remains:

- fresh HA OS App install/start;
- Integration-driven account setup;
- automatic camera/device/entity discovery;
- stable App-owned media under the final restrictive security profile;
- at least two simultaneous independent streams;
- persisted desired-running behavior survives App restart;
- no terminal/manual UID/DID/model/RTSP/YAML/Android dependency in normal use.

## Phase 6E — Home Assistant Custom Integration — ACTIVE

Foundation already live:

- Hass.io/Supervisor discovery Config Flow;
- account form and authenticated handoff;
- Config Entry without YI password;
- coordinator-driven camera inventory/status;
- 7 camera Devices with Online, Runtime status and Stream control entities;
- **Camera/live-view entities backed by the App-owned media path: PASS for tested cameras with a working upstream live source**;
- App remains the media/runtime owner; HA Core receives no direct camera credentials.

Live-view validation:

- PTZ and pool render live video in Home Assistant while their runtime diagnostics remain healthy.
- Other tested online cameras with a valid upstream live source also render through HA.
- `צד בית` currently fails to load in both Home Assistant and the official YI application, so it is excluded from the Integration live-view gate unless the upstream source starts working and HA still fails.

Next implementation target:

- polished diagnostics and reauthentication UX;
- dynamic camera additions where practical;
- removed-camera runtime cleanup;
- final secret-redaction tests.

## Phase 6F — Zero-manual-config onboarding — PLANNED

```text
Install YI RTSP
 -> Add YI Camera Connect
 -> enter YI account details / region
 -> Found N cameras
 -> Finish
```

No UID/DID/model/TNP/RTSP/YAML required from the user for Home Assistant operation.

## Phase 6G — Frigate integration/export — ACTIVE

Proven so far:

- Stable App-owned RTSP endpoints are reachable from an external Frigate host through the HA OS host-port mapping.
- External Frigate ffprobe sees H264 video and AAC audio from the App-owned RTSP path.
- Frigate live-view feeds are confirmed through the new App path for PTZ-FRONT, pool, warehouse and zforce 800.
- The old development-laptop PPPP publisher is no longer required for those migrated streams.
- Frigate remains optional and separate from the core App/Integration lifecycle.
- **Supervisor external RTSP port + LAN-host discovery: HA OS PASS.** The current installation dynamically resolved `local_yi_home`, host `10.0.0.16`, and mapped port `28554` for container `8554/tcp`.
- **Ready-to-copy per-camera Frigate RTSP URL: HA OS PASS.** `ptz-front` resolved to `rtsp://10.0.0.16:28554/yi_e2f22804fecd`.

Selected product UX:

- Users must not discover stable IDs or manually construct RTSP URLs.
- YI RTSP owns/configures external RTSP publication.
- YI Camera Connect resolves the actual HA host plus the App's mapped external RTSP port.
- Each camera exposes a ready-to-copy Frigate RTSP URL.
- The same sensor now generates a Frigate `go2rtc` YAML snippet and a readable collision-safe stream alias.
- The mapped host port is installation-specific and must never be hard-coded.

Supervisor port-discovery implementation:

- Direct Supervisor App info is used rather than the reduced higher-level AddonManager wrapper.
- The verified `aiohasupervisor` installed-App model exposes `network: dict[str, int | None] | None`.
- The Integration reads `addon_info.network` directly and extracts the host mapping for `8554/tcp`.
- Non-Supervisor installs exit cleanly with the export unavailable rather than raising or assuming a port.
- App options/credentials are not materialized or logged for port discovery.

Remaining Phase 6G gates:

- Validate the generated per-camera `frigate_stream_name` and `frigate_go2rtc` attributes on HA OS.
- Validate Stream OFF -> corresponding Frigate feed stops, then ON -> feed returns.
- Validate Frigate detection, recording and audio on the App-owned source.
- Perform final secret-redaction/export review.

See [`docs/checkpoints/2026-08-24-phase6g-supervisor-port-discovery-pass.md`](docs/checkpoints/2026-08-24-phase6g-supervisor-port-discovery-pass.md).

## Repository split / public naming

Selected public names:

```text
App:          YI RTSP
Integration:  YI Camera Connect
```

Before public distribution the monorepo will be split into independent App and Integration repositories after the cross-component API and compatibility migration are stable. See [`docs/repository-split-and-naming.md`](docs/repository-split-and-naming.md).

## Later work

- Real timestamp/timebase cleanup.
- Additional TNP profiles/model coverage.
- PTZ/camera controls where generic/safe.
- Motion/event integration.
- Reduce/eliminate QEMU where practical.
- Packaging/release automation and HACS/App repository distribution.
