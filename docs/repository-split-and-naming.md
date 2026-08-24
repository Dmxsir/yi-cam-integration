# Repository split and product naming

## Decision

Before public distribution, the current development repository will be split into two independent repositories with separate release lifecycles:

1. **Home Assistant App repository** — native/runtime/media engine.
2. **Home Assistant Custom Integration repository** — Home Assistant UI, devices, entities and onboarding.

The current `yi-cam-integration` repository remains the development monorepo until the split milestone. The split should happen only after the App/Integration API contract and the current Frigate/HA media path are sufficiently stable, so development history is not fragmented prematurely.

## Repository A — Home Assistant App

Selected product/display name: **YI RTSP**.

Suggested repository name:

```text
yi-rtsp-app
```

Responsibilities remain:

- YI account/cloud discovery backend.
- PPPP/TNP native runtime.
- capability/profile probing.
- per-camera lifecycle and recovery.
- H264/AAC relay.
- FFmpeg/go2rtc media publication.
- stable RTSP endpoints.
- authenticated local API used by the Home Assistant Integration.
- Home Assistant App packaging and App-repository distribution.

The protocol name is **RTSP** (not `RSTP`).

## Repository B — Home Assistant Custom Integration

Selected product/display name: **YI Camera Connect**.

Suggested repository name:

```text
yi-camera-connect
```

Responsibilities remain:

- Config Flow/onboarding.
- Supervisor/App discovery.
- App API client.
- Home Assistant Device Registry reconciliation.
- Camera entities.
- Online/runtime/stream entities.
- translations and diagnostics.
- reauthentication and compatibility UX.
- HACS/custom-integration distribution.

The Integration must not contain or duplicate the PPPP/TNP native runtime, QEMU runtime, FFmpeg publisher, camera credentials, or secret-bearing connection material.

## Naming constraints

Public names should avoid ambiguity with existing community/official naming:

- Do not use **YI-HACK** as the product name because that name is already established in the YI community.
- Avoid **YI Home** as the public project name because it is strongly associated with YI's official application/company branding.
- The App and Integration should be easy to distinguish in Home Assistant.

Final naming decision:

```text
App:          YI RTSP
Integration:  YI Camera Connect
```

The current development code may continue using internal `yi_home` identifiers until the explicit migration milestone. Renaming Home Assistant domains/slugs is a compatibility-sensitive change and must be handled as a migration rather than an incidental refactor.

Planned public identifiers at the repository/package split milestone:

```text
App repository:          yi-rtsp-app
App display name:        YI RTSP

Integration repository:  yi-camera-connect
Integration display name:YI Camera Connect
```

The exact final Home Assistant App slug and Custom Integration domain must be selected and migrated together with registry/config-entry compatibility handling before public release.

## Cross-repository contract

The two repositories must communicate only through the stable, versioned App API and Home Assistant Supervisor discovery contract. They should not depend on importing source files from each other.

Release compatibility should be explicit, for example:

```text
YI Camera Connect 1.x -> requires YI RTSP App >= 1.x
```

If the App API changes incompatibly, the API version must change or the Integration must provide an explicit compatibility check rather than failing indirectly.

## Distribution target

```text
YI RTSP App repository
  -> Home Assistant App repository/package

YI Camera Connect repository
  -> HACS / custom_components distribution

YI RTSP App
  <-> versioned authenticated local API
YI Camera Connect

Frigate
  -> optional consumer of YI RTSP App media endpoints
```

Frigate remains an optional consumer and must not become a dependency of either repository.
