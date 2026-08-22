# YI Home Integration – Development Plan

This document expands the high-level roadmap into the implementation order and exit gates for the remaining product work.

The target architecture remains fixed:

- **YI Home App/Add-on = engine/runtime**
- **YI Home Custom Integration = Home Assistant UI/device/entity layer**
- **Frigate = optional media consumer**

Development laptop services and hand-edited go2rtc configuration are validation infrastructure only; they are not the final deployment design.

See also [`home-assistant-app-requirements.md`](home-assistant-app-requirements.md) for the current Home Assistant 2026 App packaging/security/discovery requirements.

## Current position

Completed:

- Phase 1–2: cloud/APK/TNP research.
- Phase 3: phone-free native PPPP/TNP H264 + AAC media.
- Phase 4: Frigate interoperability.
- Phase 5: multi-camera operation and self-healing supervisor.
- Phase 6A: generic account discovery by secret-safe `stable_id`.
- Phase 6B: generic runtime path, cross-model proof, capability/profile cache.
- Phase 6C.1: versioned secret-safe backend/API skeleton and live smoke proof.
- Phase 6C.2: per-camera runtime lifecycle manager and descendant cleanup proof.
- Phase 6C.3: HTTP runtime control API for start/stop/restart.
- Phase 6C.4: HTTP live reprobe, H264/AAC capability refresh, runtime resume and cleanup proof.
- Phase 6C.5: App-owned managed go2rtc publication, two-camera operation and fault-isolated recovery.

Active work starts at **Phase 6C.6 — backend persistence and startup policy**.

---

## Phase 6C — App backend/service

### Phase 6C.1 — Backend state + HTTP API — COMPLETE

Implemented:

- Long-running backend state core.
- `GET /api/v1/health`.
- `GET /api/v1/cameras`.
- `GET /api/v1/cameras/{stable_id}`.
- `GET /api/v1/cameras/{stable_id}/status`.
- `POST /api/v1/discover`.
- Secret-safe capability data.
- Loopback default and bearer-token requirement for non-loopback binding.
- Graceful HTTP shutdown.

Live smoke result: `PHASE6C_API_SMOKE=PASS`.

### Phase 6C.2 — Per-camera runtime lifecycle manager — COMPLETE

Implemented:

- One independent runtime controller per `stable_id`.
- Generic stable-id relay path.
- Stop/restart selected camera only.
- Existing media-stall supervisor behavior preserved.
- Supervisor exit causes lifecycle recreation while desired state remains running.
- Bounded restart backoff.
- Graceful global shutdown stops every managed camera.
- Secret-safe lifecycle state.

Live PTZ proof:

- HTTP start reached `running`.
- Native media readers/mux were observed.
- Restart changed lifecycle PID.
- Stop removed the selected runtime.
- Service SIGTERM left no relay descendants.
- `PHASE6C_LIFECYCLE_SMOKE=PASS`.

### Phase 6C.3 — Runtime control API — COMPLETE

```text
POST /api/v1/cameras/{stable_id}/start
POST /api/v1/cameras/{stable_id}/stop
POST /api/v1/cameras/{stable_id}/restart
```

Implemented:

- Idempotent lifecycle behavior.
- `404` for unknown stable IDs.
- Structured runtime state.
- Per-camera operation locks serialize control/reprobe requests for the same camera.
- Different cameras remain independent.

Exit gate: PASS through HTTP-only lifecycle smoke.

### Phase 6C.4 — Reprobe + capability refresh — COMPLETE

Implemented:

- `yi_capability_probe_runtime.py` reusable bounded live-probe core.
- `POST /api/v1/cameras/{stable_id}/reprobe` performs a real live probe.
- Running camera is isolated before reprobe and restored afterward.
- Probe uses the same continuous MPEG-TS stdout path as normal streaming.
- Capability success is based on observed H264 + AAC media, not camera model or relay shutdown timing.
- Capability cache updates atomically only on proof success.
- Previous proven records survive failed probes.
- Probe process groups are bounded and cancelled on App shutdown.
- Secret-safe diagnostics and isolated smoke-test cache.

Live PTZ exit-gate proof (2026-08-23):

- Initial HTTP-started runtime reached native media.
- HTTP reprobe passed on attempt 1.
- Capability source became `addon_api_reprobe`.
- H264 1920x1080 + AAC 16000 Hz mono validated.
- Isolated cache readback passed.
- Runtime resumed with a new PID and reached native media again.
- Stop, graceful shutdown and probe cleanup passed.
- `PHASE6C_REPROBE_SMOKE=PASS`.

### Phase 6C.5 — App-owned media publication — COMPLETE

Architecture:

```text
per-camera Lifecycle Manager
        |
        | supervised MPEG-TS stdout
        v
HTTP incoming MPEG-TS ingest
        |
        v
shared App-managed go2rtc
        |
        +--> RTSP /yi_<stable-id-prefix>
        +--> future HA/WebRTC consumer path
        +--> optional Frigate
```

Implemented reusable backend pieces:

- `yi_stream_identity.py` — immutable media stream names derived only from `stable_id`.
- `yi_media_publisher.py` — managed shared go2rtc process and generated empty-stream configuration.
- Lifecycle manager pushes supervised MPEG-TS directly to managed go2rtc using chunked HTTP streaming.
- Backend exposes secret-safe publication metadata alongside camera/runtime state.
- Publisher readiness distinguishes a registered producer from one with actual detected media.
- First MPEG-TS data is prebuffered before incoming HTTP ingest so go2rtc's probe window is used for transport data rather than PPPP/TNP startup.

Stable identity example:

```text
stable_id:   e2f22804fecdbd8c3561
stream:      yi_e2f22804fecd
RTSP path:   /yi_e2f22804fecd
```

#### Phase 6C.5A — isolated publisher proof — COMPLETE

Live PTZ proof (2026-08-23):

- Separate backend and managed go2rtc ran on isolated ports.
- Generated publisher contained all 7 camera destinations.
- Production ports `1984/8554` remained untouched.
- HTTP camera start attached lifecycle MPEG-TS ingest.
- Producer became registered and media-ready.
- RTSP validated H264 1920x1080 + AAC 16000 Hz mono.
- HTTP restart changed camera runtime PID from `10651` to `10737`.
- Shared go2rtc PID did not change.
- Producer re-registered media-ready and RTSP recovered.
- `PHASE6C_MEDIA_PUBLISHER_SMOKE=PASS`.

#### Phase 6C.5B — two-camera + fault isolation — COMPLETE

Live PTZ + pool proof (2026-08-23):

- Isolated backend/go2rtc ports were `18103/11985/18555`; production remained untouched.
- PTZ `e2f22804fecdbd8c3561` and pool `867ecdee5a3692c669f9` started concurrently.
- Both publications became media-ready and both RTSP endpoints validated H264 + AAC.
- Fault injection froze only the PTZ relay process group (`PGID 11282`).
- Pool RTSP remained valid during the PTZ fault.
- PTZ runtime PID changed `11272` → `11588`; generation changed `1` → `2`.
- Pool runtime PID/generation stayed unchanged.
- Shared go2rtc PID stayed unchanged.
- Faulted descendants were cleaned.
- Both RTSP endpoints validated H264 + AAC after recovery.
- Both runtimes stopped cleanly and publisher cleanup passed.
- `PHASE6C_MEDIA_ISOLATION_SMOKE=PASS`.

Exit gate: PASS. Phase 6C.5 is complete.

### Phase 6C.6 — Backend persistence and startup policy — ACTIVE

Goal: make the backend restart-safe before packaging it as a Home Assistant App.

Policy decision:

- Runtime startup is **explicit-intent based**, not "start every discovered camera".
- `start` and `restart` persist `desired_running=true` for that immutable `stable_id`.
- `stop` removes persisted running intent.
- Newly discovered cameras default to stopped until the Integration/user requests start.
- Reprobe temporary stop/resume does not alter persisted intent.

Persistence layout when `yi_addon_service.py --data-dir <path>` is enabled:

```text
<data-dir>/capabilities.json
<data-dir>/runtime-policy.json
<data-dir>/runtime/
<data-dir>/publisher/
```

The Home Assistant App will later use `--data-dir /data`.

Implemented so far:

- `yi_runtime_policy.py`
  - schema-versioned secret-safe runtime intent.
  - stores only `stable_id` values that should run.
  - atomic fsync + replace writes.
  - file mode 0600 and parent mode 0700 where supported.
- `yi_persistent_backend.py`
  - persistence adapter around the already-proven `YiAddonBackend`.
  - runtime intent is persisted before start/stop/restart control is applied.
  - successful discovery reconciles persisted intent against current camera inventory.
  - unavailable/missing intended cameras remain pending rather than being deleted.
  - health exposes desired count, pending restore count, last reconcile time/counts and safe policy errors.
  - camera/status responses expose `persisted_desired_running`.
- `yi_addon_service.py`
  - new `--data-dir` option.
  - explicit per-feature paths still take precedence where applicable.
  - no `--data-dir` keeps legacy non-persistent smoke behavior unchanged.
  - initial discovery failure no longer risks losing intent.
  - automatic bounded-interval initial-discovery retry is enabled by `--discovery-retry-interval` (default 30s) until the first successful discovery.
- Regression tests:
  - persistence round-trip and mode 0600.
  - unavailable intended camera remains pending.
  - simulated cloud discovery failure leaves persisted intent pending.
- Live validation adapter:
  - `tools/phase3_pppp_probe/run_phase6c_persistence_smoke.sh`.

Live 6C.6 exit-gate design:

1. Start isolated backend/go2rtc with a temporary persistent data directory.
2. Start PTZ + pool and validate both RTSP streams.
3. Run a real live reprobe so `capabilities.json` is proven under the data directory while runtime intent remains unchanged.
4. Shut down the whole service **without** stopping either camera through the API.
5. Restart with the same data directory and require both cameras to restore automatically and both RTSP streams to return.
6. Explicitly stop pool and verify policy now contains only PTZ.
7. Shut down and restart a third time.
8. Require PTZ to restore automatically while pool remains persistently stopped.
9. Verify secret-safe mode-0600 state and final service/publisher cleanup.

Cloud-outage boot behavior:

- Initial discovery exceptions keep the HTTP service alive.
- Persisted desired IDs remain pending.
- A background retry loop repeats initial discovery at the configured interval.
- The first later successful discovery runs the same reconcile path and restores intended cameras.
- Regression coverage proves a discovery transport failure does not clear pending intent.

Exit gate:

- `PHASE6C_PERSISTENCE_SMOKE=PASS` from the live restart sequence.
- Persistence regression tests pass.
- No production go2rtc/systemd configuration is modified.

Phase 6C is complete only after 6C.6 passes.

---

## Phase 6D — Home Assistant App/Add-on packaging

Goal: move the engine from development infrastructure into HA OS/Supervisor.

### 6D.1 Container/runtime packaging

- App repository/folder structure.
- `config.yaml`, Dockerfile, startup script and AppArmor profile.
- Explicit reproducible Docker base image.
- Python backend and native runtime included.
- QEMU/libPPPP/FFmpeg/go2rtc packaged explicitly.
- No development-machine paths.
- Initial architecture target `amd64`; add `aarch64` only after proof.

### 6D.2 Configuration, storage and secrets

- Persistent `/data` capability/runtime state.
- App-generated internal backend API token stored mode 0600 under `/data`.
- Supervisor discovery passes only internal API connection metadata/token to the Integration.
- YI credentials never appear in discovery/logs/read APIs/diagnostics.
- Integration sends YI account credentials through authenticated internal API.

### 6D.3 Networking and health

- `host_network: false`.
- No `full_access`, Docker API or Home Assistant config-directory mapping.
- Backend API internal to the App network.
- RTSP host exposure only when required for external consumers.
- Supervisor watchdog tied to backend health.

### 6D.4 Architecture support

- Verify packaged native/QEMU path on each advertised architecture.
- Fail clearly on unsupported architecture.

Exit gate:

- Fresh HA OS App install starts successfully.
- Discovery returns account cameras.
- At least two streams are served directly from the App.
- App restart restores operation.

---

## Phase 6E — Home Assistant Custom Integration

### Phase 6E.1 — Config Flow

- Consume Supervisor/App discovery through `async_step_hassio`.
- Validate backend API version and health.
- Guide account setup without exposing PPPP/TNP internals.

### Phase 6E.2 — Device Registry

- One HA Device per camera.
- Unique identity based on `stable_id`.
- Camera rename does not create a new device.

### Phase 6E.3 — Entities

- `camera` entity.
- runtime/connectivity status.
- cloud-online state.
- restart/reprobe controls where useful.

### Phase 6E.4 — Diagnostics

- App/API version.
- Safe camera metadata.
- Runtime/restart counters.
- Capability/publication state.
- Explicit redaction tests.

Exit gate:

- Add Integration → YI Home creates devices/entities automatically and live view works without YAML.

---

## Phase 6F — Zero-manual-config onboarding

```text
Install YI Home App
  -> Add YI Home Integration
  -> App discovered automatically
  -> enter YI account / region
  -> Found N cameras
  -> Finish
```

No UID/DID/model/TNP/RTSP/YAML required.

---

## Phase 6G — Frigate integration/export

- Stable App-owned RTSP URLs.
- Safe generated example/config helper.
- H264 + AAC recording path.
- Frigate absence/failure never affects core Home Assistant camera support.

---

## Post-product enhancements

- Native timestamp/timebase cleanup.
- More protocol/profile coverage.
- PTZ/camera controls.
- Motion/event integration.
- Reduce/eliminate QEMU where practical.
- Release automation, versioning, App repository and HACS distribution.

## Engineering rule

Every new Phase 6 feature is reusable App/backend functionality first. Development CLIs and shell scripts remain validation adapters and must never become required parts of the final Home Assistant UX.
