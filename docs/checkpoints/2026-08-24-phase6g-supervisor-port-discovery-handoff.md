# Phase 6G checkpoint — Supervisor RTSP port discovery handoff

Date: 2026-08-24
Branch: `phase-3-linux-pppp`

## Purpose

This checkpoint is the handoff point before continuing in a new conversation. Phase 6G Frigate export is active and the next implementation task is automatic discovery of the YI RTSP App's externally mapped RTSP host port.

## Current product names

```text
App:          YI RTSP
Integration:  YI Camera Connect
```

The current development code intentionally still uses internal `yi_home` identifiers. Domain/slug migration is deferred until the explicit compatibility-sensitive repository split/public-release milestone.

Planned repositories:

```text
yi-rtsp-app
yi-camera-connect
```

## Media / Frigate status

Validated topology:

```text
YI camera
  -> YI RTSP App runtime
  -> App-owned go2rtc RTSP publication
  -> HA OS host-port mapping
  -> external Frigate
  -> Frigate go2rtc
  -> Frigate live view
```

Confirmed through the new App-owned path:

- PTZ-FRONT
- pool
- warehouse
- zforce 800

External ffprobe previously confirmed H264 video plus AAC audio from the YI RTSP App path.

The current validation installation maps container `8554/tcp` to host port `28554`, but **28554 is installation-specific and must never be hard-coded into the product**.

Current runtime policy remains explicit:

- YI RTSP owns the camera runtime.
- Frigate is only a consumer.
- The camera Stream switch / desired-running state must be ON for continuous Frigate consumption.
- Frigate does not currently start a stopped runtime on demand.

## Frigate export UX decision

Users must not inspect stable IDs, entity registries or manually assemble RTSP URLs.

YI Camera Connect should eventually present a ready-to-copy URL per camera:

```text
rtsp://<reachable-HA-host>:<mapped-YI-RTSP-port>/yi_<stable-prefix>
```

It should also generate a Frigate `go2rtc` snippet for eligible cameras.

The readable Frigate stream alias may be based on the camera display name, while the upstream RTSP path must remain stable-ID based so user-visible camera renames do not break Frigate.

## Existing Integration behavior relevant to this work

`custom_components/yi_home/config_flow.py` already accepts `rtsp_port` from Hass.io discovery and stores it in the Config Entry when the discovery payload includes it:

```python
if CONF_RTSP_PORT in self._discovery:
    data[CONF_RTSP_PORT] = int(self._discovery[CONF_RTSP_PORT])
```

`CONF_RTSP_PORT = "rtsp_port"` is already defined in `custom_components/yi_home/const.py`.

Important distinction: the discovery-provided `rtsp_port` represents the App-side/internal RTSP service port. It is not sufficient for an external Frigate host when HA OS maps that container port to a different host port.

## Supervisor research completed at this checkpoint

Home Assistant Supervisor's App info API exposes the installed App network mapping as:

```python
ATTR_NETWORK: app.ports
```

The Supervisor App options API also accepts `network` and applies it to `app.ports`.

Therefore the authoritative external port mapping is available from Supervisor and automatic resolution is viable.

Home Assistant Core's `AddonManager.async_get_addon_info()` wrapper currently converts Supervisor App info into its own `AddonInfo` dataclass containing fields such as hostname/options/state/version, but that wrapper does **not** retain the App network/ports mapping.

Implication: the YI integration will probably need to query the Supervisor client directly for the installed App info rather than relying only on the higher-level `AddonManager` wrapper.

No production implementation of that lookup has been committed yet at this checkpoint.

## Next implementation task

Implement a small secret-safe Supervisor helper in YI Camera Connect that:

1. Runs only on HA OS / Supervised installs where Supervisor is available.
2. Resolves the installed YI RTSP App by its current development slug (`local_yi_home` for the local test App; public slug migration comes later).
3. Reads the App's authoritative `network`/ports mapping from Supervisor.
4. Extracts the host-side mapping corresponding to container `8554/tcp`.
5. Returns `None` cleanly when the port is not exposed externally, rather than assuming a default.
6. Never logs App options, credentials, bearer tokens, YI UID/DID, account information or other secret-bearing material.
7. Has unit tests covering mapped, unmapped, malformed and Supervisor-unavailable cases.

Before coding against a model attribute name, inspect the actual `aiohasupervisor` installed-App model returned by `get_supervisor_client(hass).addons.addon_info(...)`; do not guess the field shape.

## Following implementation steps

Once the external host port is resolved reliably:

- resolve a reachable HA host/IP suitable for LAN Frigate access;
- construct a ready-to-copy RTSP URL for each camera using the stable stream path;
- expose the URL through YI Camera Connect UX without changing camera/entity unique IDs;
- generate a Frigate `go2rtc` YAML export/snippet;
- validate Stream OFF -> Frigate feed stops, ON -> feed returns;
- validate Frigate detection, recording and audio on the App-owned source;
- perform final secret-redaction review.

## Repository split decision

Do not split repositories yet. The monorepo remains the development source until the App/Integration API and compatibility migration are stable.

Final intended split:

```text
YI RTSP App repository
  -> yi-rtsp-app

YI Camera Connect repository
  -> yi-camera-connect
```

The two repositories must communicate only through the versioned authenticated App API / Supervisor discovery contract and must have independent release lifecycles.

## Key recent commits

```text
184d8b6  Select YI Camera Connect integration name
5e6cfb6  Record Phase 6G Frigate export UX and validation
08e9b8a  Advance Phase 6G Frigate export and public naming
```

## Resume point

In the next conversation, start with **Phase 6G Supervisor external RTSP port discovery**. Do not re-open the solved media relay, branding, naming or Frigate basic-live-view work unless a regression is observed.
