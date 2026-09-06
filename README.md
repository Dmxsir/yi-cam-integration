# YI Home for Home Assistant

![YI Home](custom_components/yi_home/brand/icon.png)

Experimental Home Assistant integration for YI Home cameras.

This project is split into two repositories:

- **`Dmxsir/yi-cam-integration`** — the Home Assistant custom integration, installed through HACS.
- **`Dmxsir/yi-rtsp`** — the Home Assistant App that runs the YI camera runtime and publishes the internal API / RTSP service used by the integration.

> **Status:** Experimental. The project is under active development and currently targets the YI Home camera runtime that has been validated during the reverse-engineering work. Expect breaking changes while the integration is being completed.

## Architecture

```text
YI cameras / YI services
        |
        v
YI RTSP Home Assistant App (Dmxsir/yi-rtsp)
        |
        | authenticated internal API + RTSP
        v
YI Home custom integration (this repository)
        |
        v
Home Assistant devices and entities
```

The custom integration does **not** contain the proprietary YI runtime. The companion Home Assistant App is responsible for that runtime and exposes only the local service interface required by Home Assistant.

## Installation

### 1. Install the YI RTSP Home Assistant App

Add this repository to **Settings → Apps → App store → Repositories**:

```text
https://github.com/Dmxsir/yi-rtsp
```

Install **YI RTSP** and start it.

### 2. Install this integration with HACS

In HACS:

1. Open **Custom repositories**.
2. Add:

```text
https://github.com/Dmxsir/yi-cam-integration
```

3. Select **Integration** as the repository type.
4. Add the repository and download **YI Home**.
5. Restart Home Assistant when HACS asks you to do so.

### 3. Add the integration

After the App is running and the HACS integration is installed:

1. Open **Settings → Devices & services**.
2. Select **Add integration**.
3. Search for **YI Home**.

The intended setup path uses Home Assistant Supervisor discovery from the YI RTSP App, so the App and integration can exchange the local backend connection metadata without exposing the YI account credentials through discovery.

## Current capabilities

The integration code currently contains support for:

- Home Assistant config flow and Supervisor discovery.
- Camera entities.
- Sensors and binary sensors.
- Switch entities.
- Communication with the companion YI Home backend API.
- RTSP export plumbing for Home Assistant camera use.

Some camera/account workflows are still experimental and are being validated before the project is considered stable.

## Requirements

- Home Assistant OS / supervised environment for the companion App workflow.
- HACS for convenient installation of this custom integration.
- The **YI RTSP** companion App from `Dmxsir/yi-rtsp`.
- A supported YI Home camera/account configuration.

## Troubleshooting

### The repository was added to HACS but YI Home is not visible

Confirm that:

- The repository is public.
- It was added as repository type **Integration**.
- HACS has refreshed the repository information after it was made public.
- `custom_components/yi_home/manifest.json` is present in the downloaded repository.

If the repository was previously private, remove the custom repository entry from HACS, restart/refresh HACS if necessary, then add it again as an **Integration**.

### YI Home does not appear under Add integration

Download the integration in HACS and restart Home Assistant. If it still does not appear, clear/reload the browser frontend cache and check the Home Assistant logs for `custom_components.yi_home`.

### Discovery points to the wrong App hostname

The current App repository uses the Supervisor-generated hostname associated with the App repository slug. Make sure the latest **YI RTSP** App version is installed before troubleshooting discovery.

## Development status

This repository originated from protocol research and reverse engineering of the YI Home ecosystem. Research/probe utilities are intentionally kept separate from the runtime Home Assistant component where possible. The public integration interface is being tightened as the App/API contract stabilizes.

## Issues

Please report reproducible problems here:

https://github.com/Dmxsir/yi-cam-integration/issues

When reporting an issue, include the Home Assistant version, YI Home integration version, YI RTSP App version, camera model, and relevant logs with credentials/tokens removed.

## Disclaimer

This is an independent community project and is not affiliated with or endorsed by YI Technology. YI and YI Home are trademarks of their respective owners.
