# Phase 6G checkpoint — Frigate RTSP export

Date: 2026-08-24

## Status

Phase 6G is now **ACTIVE** with a real external Frigate media path proven from the Home Assistant App.

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

The external RTSP media path has been validated with H264 video and AAC audio at the transport level. Frigate live-view feeds are currently confirmed for PTZ-FRONT, pool, warehouse and zforce 800 using the App-owned RTSP path rather than the previous development-laptop PPPP publisher.

The current HA OS validation environment maps the App's internal RTSP port to a free host port. This port value is installation-specific and must never be hard-coded as a product assumption.

## Stable stream identity

The media path uses the secret-safe stable camera identity rather than the user-visible camera name.

Conceptually:

```text
rtsp://<HA-host>:<mapped-RTSP-port>/yi_<stable-prefix>
```

Renaming a camera must not alter this RTSP path. The already-proven Home Assistant rename behavior therefore also protects Frigate configuration from user-visible camera renames.

## Final user experience decision

Users must not be expected to discover a stable ID, inspect Home Assistant registries or manually construct an RTSP URL.

Selected UX direction:

### YI RTSP App

The App owns external RTSP publication and exposes/configures the host-facing RTSP port mapping.

Conceptual UI:

```text
External RTSP access: enabled
External RTSP port: <mapped host port>
```

The actual mapped host port is installation-specific. The Integration must resolve the current App/Supervisor mapping rather than assuming a fixed value.

### YI Camera Connect

For every camera, the Integration should expose a ready-to-copy Frigate/RTSP endpoint built from:

```text
Home Assistant reachable host/IP
+ current external YI RTSP host port
+ stable App-owned camera stream path
```

The user-facing result should be equivalent to:

```text
Frigate RTSP
rtsp://<HA-host>:<port>/yi_<stable-prefix>
```

The user should never need to know how the path is generated.

## Frigate export helper

YI Camera Connect should also offer a generated Frigate snippet for all eligible cameras, for example:

```yaml
go2rtc:
  streams:
    camera_name: rtsp://<HA-host>:<port>/yi_<stable-prefix>
```

The generated stream key may use a safe readable camera slug because it is only the local Frigate alias. The upstream RTSP path remains stable-ID based.

This export is a convenience feature only. Frigate remains optional and is not a dependency of either YI RTSP or YI Camera Connect.

## Runtime policy

Current behavior remains explicit:

- YI RTSP owns the camera runtime.
- Frigate is only a media consumer.
- A camera's Stream switch/desired-running state must be enabled for continuous Frigate consumption.
- Frigate does not currently start a stopped YI runtime on demand.

A future release may add an explicit continuous-export policy, but it must not be inferred implicitly from a failed RTSP connection.

## Remaining Phase 6G gates

Before Phase 6G is marked COMPLETE:

1. Prove Stream OFF causes the corresponding new App-owned Frigate feed to stop, and ON restores it, demonstrating no legacy publisher dependency.
2. Validate Frigate detect on the new source.
3. Validate recording on the new source.
4. Validate audio handling/recording where enabled.
5. Implement reliable discovery of the App's externally mapped RTSP port.
6. Expose ready-to-copy per-camera RTSP URLs in YI Camera Connect.
7. Add generated Frigate `go2rtc` export/snippet UX.
8. Keep exported data secret-safe and avoid exposing cloud UID/DID/account credentials/tokens.

## Naming

Public product names selected for the eventual repository split are:

```text
App:          YI RTSP
Integration:  YI Camera Connect
```

The current internal `yi_home` identifiers remain unchanged until the explicit compatibility-sensitive rename/repository-split migration.
