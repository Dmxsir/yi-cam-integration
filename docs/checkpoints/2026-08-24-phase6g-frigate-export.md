# Phase 6G checkpoint — Frigate RTSP export

Date: 2026-08-24

## Status

Phase 6G is **ACTIVE** with the external Frigate export discovery, generated `go2rtc` UX, runtime ownership, detection and recording behavior validated on the real Home Assistant OS installation.

Validated topology:

```text
YI camera
  -> YI RTSP App runtime
  -> App-owned go2rtc / RTSP publication
  -> Home Assistant OS host port mapping
  -> external Frigate host
  -> Frigate go2rtc
  -> Frigate live view / detection / recording
```

The external RTSP media path has been validated with H264 video and AAC audio at the transport level. Frigate live-view feeds are confirmed for PTZ-FRONT, pool, warehouse and zforce 800 using the App-owned RTSP path rather than the previous development-laptop PPPP publisher.

## Stable stream identity

The media path uses the secret-safe stable camera identity rather than the user-visible camera name:

```text
rtsp://<HA-host>:<mapped-RTSP-port>/yi_<stable-prefix>
```

Renaming a camera does not alter this upstream RTSP path. A readable Frigate alias is generated separately from the camera display name.

## HA OS Supervisor discovery validation — PASS

The Custom Integration now resolves the authoritative external RTSP mapping from Supervisor App info rather than assuming a fixed host port.

Real HA OS validation result for `ptz-front`:

```text
external_rtsp_port: 28554
external_host: 10.0.0.16
app_slug: local_yi_home
requires_stream_enabled: true
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

This proves the current installation's actual `8554/tcp` host mapping is discovered at runtime. `28554` remains installation-specific and is not a product constant.

Implementation details:

- Config Flow persists the real Supervisor App slug from `HassioServiceInfo.slug` for newly-created entries.
- Existing entries recover the originating App slug from Supervisor discovery, with compatibility fallbacks for current development/public slug names.
- Integration setup reads the actual `8554/tcp` host mapping from Supervisor App `network` data.
- The LAN host prefers the primary IPv4 address reported by Supervisor network info, with Home Assistant internal-URL/local-IP fallbacks.
- Runtime export data is separate from the App's internal Supervisor-network RTSP endpoint used by Home Assistant live view.
- Every YI camera exposes a `Frigate RTSP` sensor with a ready-to-copy external URL when the App port is mapped.
- Existing config entries store only the secret-safe App slug; no YI credentials or media secrets are added.
- Non-Supervised Home Assistant returns an unavailable export cleanly rather than failing setup.

## Generated Frigate `go2rtc` export — PASS

The `Frigate RTSP` sensor also generates a safe readable Frigate stream alias and a ready-to-copy `go2rtc` YAML snippet.

Validated HA OS result for `ptz-front`:

```text
frigate_stream_name: ptz_front
frigate_go2rtc: |-
  go2rtc:
    streams:
      ptz_front: rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

The readable `ptz_front` key is only the local Frigate alias. The upstream path remains stable-ID based. Duplicate readable camera names are disambiguated with a short stable-ID suffix.

Frigate remains optional and is not a dependency of either YI RTSP or YI Camera Connect.

## Stream OFF / ON runtime ownership validation — PASS

Controlled validation used `ptz-front` with Frigate already showing live video from the generated App-owned RTSP URL.

Observed behavior:

1. Before the test, Frigate displayed live video for `ptz_front`.
2. Turning the YI Camera Connect `Stream` switch OFF moved the camera runtime to `STOPPED`.
3. The corresponding Frigate feed stopped.
4. Turning the same `Stream` switch ON restarted the App-owned camera runtime.
5. The same Frigate feed recovered automatically without any Frigate restart and without any URL/YAML change.
6. Recovery on the current installation took roughly one minute. This is recorded as observed recovery latency, not a gate failure.

This proves Frigate is consuming the App-owned publisher controlled by YI Camera Connect and that no legacy development publisher remains in the active media path.

## Frigate detection and recording validation — PASS

With `ptz-front` running through the generated App-owned RTSP source, a real person/motion pass in front of the camera produced Frigate detection and corresponding recordings.

Observed behavior:

- Frigate detection/event generation works on the App-owned source.
- Recordings are being created for the camera while using the same generated RTSP path.
- Live view remained available through the same Frigate stream configuration.

This closes the Phase 6G detection and recording gates without reverting to the legacy publisher or changing the generated upstream URL.

## Runtime policy

Current behavior remains explicit:

- YI RTSP owns the camera runtime.
- Frigate is only a media consumer.
- A camera's Stream switch/desired-running state must be enabled for continuous Frigate consumption.
- Frigate does not start a stopped YI runtime on demand.

## Phase 6G gate status

1. Stream OFF -> Frigate feed stops; ON -> feed returns: **PASS**.
2. Frigate detect on the new App-owned source: **PASS**.
3. Frigate recording on the new App-owned source: **PASS**.
4. Audio handling/recording where enabled: **PENDING**.
5. HA OS external RTSP host/port discovery: **PASS**.
6. HA OS per-camera ready-to-copy RTSP sensor: **PASS**.
7. Generated Frigate `go2rtc` export/snippet UX: **PASS**.
8. Secret-safe export/diagnostic review: **IN PROGRESS**.

## Next validation

Use `ptz-front` for the remaining Frigate media gate:

1. Open a recent Frigate recording/event clip from `ptz_front`.
2. Verify the clip contains usable audio from the YI camera where Frigate audio is enabled.
3. If audio is absent, inspect Frigate/go2rtc media information before changing the upstream RTSP URL.
4. After audio passes, perform the final secret-safe export/diagnostic review before marking Phase 6G complete.

## Naming

Public product names selected for the eventual repository split are:

```text
App:          YI RTSP
Integration:  YI Camera Connect
```

The current internal `yi_home` identifiers remain unchanged until the explicit compatibility-sensitive rename/repository-split migration.
