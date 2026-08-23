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
- Persistent `/data`, protected/AppArmor operation and least-privilege networking proven.
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

#### One-camera HA OS long-run gate — ACTIVE / FAILING

HA OS still shows runtime recreation after longer operation, including both watchdog `exit=75` and relay `exit=1` observations.

The same exact pinned image has now passed two independent 10-minute development-host tests:

```text
Docker host networking:   generation=1, restart_count=0, 93,192,192 bytes
Docker bridge/NAT:        generation=1, restart_count=0, 81,264,640 bytes
```

The bridge test showed continuous PPPP/TNP authentication/media progress through the full 600-second window, so ordinary Docker bridge/NAT is ruled out as the cause.

Current conclusion:

- FFmpeg 6.0.1 fixes the original early FFmpeg 8 regression.
- The pinned application/runtime stack is stable for at least ten minutes both with host networking and ordinary Docker bridge/NAT outside HA OS.
- The unresolved failure is HA OS/App-environment specific.
- Leading remaining categories: AppArmor/protected mode, HA OS/Supervisor-specific firewall/network behavior beyond ordinary Docker bridge, cgroup/resource scheduling/host pressure, or another HA OS runtime constraint.
- **Do not start the multi-camera HA OS gate yet.**

Next gate:

1. Collect read-only HA OS host/Supervisor evidence around a one-camera failure for AppArmor denials, OOM/killed-process events, cgroup/resource pressure and YI/QEMU/FFmpeg references.
2. If the logs identify a denial/resource event, follow that evidence directly.
3. If host logs are clean, run a temporary one-variable HA OS A/B with AppArmor disabled for the local development App only, while preserving bridge networking and the media/runtime configuration.
4. Restore the security profile immediately after the diagnostic run.
5. Only after long-run one-camera HA OS stability is proven should two-camera HA OS testing resume.

### Phase 6D.4 — Architecture support — PLANNED

- Initial target remains `amd64` only.
- Advertise `aarch64` only after independent full native/QEMU proof.

Phase 6D exit gate remains:

- fresh HA OS App install/start;
- Integration-driven account setup;
- automatic camera/device/entity discovery;
- long-running stable App-owned media;
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
