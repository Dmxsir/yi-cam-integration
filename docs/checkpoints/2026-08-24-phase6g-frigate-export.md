# Phase 6G checkpoint — Frigate RTSP export

Date: 2026-08-24

## Status

Phase 6G is **ACTIVE** with the external Frigate export discovery and generated `go2rtc` UX validated on the real Home Assistant OS installation.

Validated topology:

```text
YI camera
  -> YI RTSP App runtime
  -> App-owned go2rtc / RTSP publication
  -> Home Assistant OS host port mapping
  -> external Frigate host
  -> Frigate go2rtc
  -> Frigate live view
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

## Runtime policy

Current behavior remains explicit:

- YI RTSP owns the camera runtime.
- Frigate is only a media consumer.
- A camera's Stream switch/desired-running state must be enabled for continuous Frigate consumption.
- Frigate does not start a stopped YI runtime on demand.

## Phase 6G gate status

1. Stream OFF -> Frigate feed stops; ON -> feed returns: **PENDING**.
2. Frigate detect on the new App-owned source: **PENDING**.
3. Frigate recording on the new App-owned source: **PENDING**.
4. Audio handling/recording where enabled: **PENDING**.
5. HA OS external RTSP host/port discovery: **PASS**.
6. HA OS per-camera ready-to-copy RTSP sensor: **PASS**.
7. Generated Frigate `go2rtc` export/snippet UX: **PASS**.
8. Secret-safe export/diagnostic review: **IN PROGRESS**.

## Next validation

Use `ptz-front` as the controlled test stream:

1. Confirm Frigate is consuming `ptz_front` from the generated App-owned RTSP URL.
2. Turn the YI Camera Connect `Stream` switch for `ptz-front` OFF.
3. Verify the App runtime stops and Frigate loses only that corresponding feed.
4. Turn the switch ON.
5. Verify the runtime restarts and the same Frigate stream recovers without changing URL or YAML.

This test demonstrates that Frigate is consuming only the App-owned publisher and that no legacy development publisher remains in the path.

## Naming

Public product names selected for the eventual repository split are:

```text
App:          YI RTSP
Integration:  YI Camera Connect
```

The current internal `yi_home` identifiers remain unchanged until the explicit compatibility-sensitive rename/repository-split migration.
