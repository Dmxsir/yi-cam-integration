# YI Home for Home Assistant

![YI Home](custom_components/yi_home/brand/icon.png)

YI Home is a Home Assistant custom integration for supported YI Home cameras. It works together with the companion **YI RTSP** Home Assistant App.

This project is split into two repositories:

- **`Dmxsir/yi-cam-integration`** — this repository. The Home Assistant custom integration, installed through HACS.
- **`Dmxsir/yi-rtsp`** — the Home Assistant App that runs the YI camera PPPP/TNP runtime and publishes the internal API and RTSP service used by this integration.

> **Status:** experimental but working end-to-end on the validated YI Home camera setup. Expect changes while support is expanded to additional models/configurations.

## Architecture

```text
YI cameras / YI services
        |
        v
YI RTSP Home Assistant App
        |
        | authenticated internal API + RTSP
        v
YI Home custom integration
        |
        +--> Home Assistant camera/entities
        |
        +--> Frigate RTSP sensor / go2rtc configuration
```

The custom integration does **not** contain or distribute the proprietary YI PPPP runtime. The companion App imports the required library locally from the user's own official YI Home APK.

---

# Installation

## 1. Install the YI RTSP Home Assistant App

In Home Assistant open:

**Settings → Apps → App Store → ⋮ → Repositories**

Add:

```text
https://github.com/Dmxsir/yi-rtsp
```

Install and start **YI RTSP**.

On first start open:

**YI RTSP → Open Web UI**

Upload your own official YI Home APK. The App extracts and validates the required ARM64 `libPPPP_API.so`, stores it privately under `/data`, deletes the temporary APK, and continues startup automatically.

For full App/APK instructions and troubleshooting see:

https://github.com/Dmxsir/yi-rtsp

## 2. Install this integration with HACS

In HACS:

1. Open **Custom repositories**.
2. Add:

```text
https://github.com/Dmxsir/yi-cam-integration
```

3. Select **Integration** as the repository type.
4. Add the repository and install **YI Home**.
5. Perform a **full Home Assistant restart**.

## 3. Configure from Supervisor Discovery

Initial setup is performed through **Home Assistant Supervisor Discovery** from the YI RTSP App.

Do **not** use **Add integration → YI Home** for the initial setup. Manual setup is intentionally disabled and will abort because the integration requires App discovery metadata.

After Home Assistant restarts and YI RTSP is running, open:

**Settings → Devices & services**

You should see **YI Home** under **Discovered**.

Press **Configure**.

Enter your YI account details and select the matching country/region. For example:

```text
Country: IL
Region: Europe
```

Use the region associated with your actual YI account.

The YI account/password are sent directly to the companion App for validation and are intentionally **not stored in the Home Assistant config entry**.

After successful configuration, Home Assistant creates the available YI camera devices and entities.

---

# Frigate / RTSP

The YI RTSP App publishes RTSP internally on TCP `8554`.

To expose RTSP to Frigate or another LAN client, configure a host-port mapping in the **YI RTSP App → Network** section, for example:

```text
8554/tcp -> 28554
```

`28554` is only an example. Any unused TCP host port can be used.

After changing the mapping:

1. restart YI RTSP;
2. reload this YI Home integration, or restart Home Assistant.

Each camera exposes a **Frigate RTSP** sensor when an external RTSP port is available.

The sensor state is the complete ready-to-copy external RTSP URL. The path is generated from the camera's stable ID, so **do not construct it manually**.

The sensor also exposes:

```text
external_rtsp_port
external_host
app_slug
requires_stream_enabled
frigate_stream_name
frigate_go2rtc
```

The `frigate_go2rtc` attribute contains a ready-to-copy go2rtc YAML snippet for the camera.

Example structure:

```yaml
go2rtc:
  streams:
    my_yi_camera:
      - rtsp://HOME_ASSISTANT_IP:28554/yi_<camera-id>
      - "ffmpeg:my_yi_camera#audio=opus"
```

Prefer using the generated sensor value/attribute rather than typing the example manually.

---

# Current capabilities

The integration currently supports:

- Supervisor Discovery from the companion YI RTSP App.
- YI account configuration and reauthentication through the App.
- Camera entities.
- Runtime/status sensors.
- Binary sensors and switches exposed by supported camera data.
- Managed camera streaming through the companion App.
- External RTSP export discovery.
- Ready-to-copy Frigate/go2rtc configuration metadata.

---

# Requirements

- Home Assistant OS / supervised environment with Apps support.
- `amd64` for the current YI RTSP App build.
- HACS for installation of this custom integration.
- The **YI RTSP** companion App from `Dmxsir/yi-rtsp`.
- A supported YI Home camera/account configuration.
- The user's own official YI Home APK for first-time App runtime import.

---

# Troubleshooting

## YI Home does not appear under Discovered

Confirm that:

- YI RTSP is running;
- its log contains `Published YI Home discovery information to Home Assistant`;
- this HACS integration is installed;
- Home Assistant was fully restarted after HACS installation.

If needed, restart YI RTSP once and then restart Home Assistant.

## Add integration shows `app_required`

This is expected if YI Home is opened manually from **Add integration**.

Initial configuration must start from the **Discovered** YI Home card published by the companion App.

## `Failed setup, will retry: YI Home App is not ready`

Confirm that the companion App log reaches:

```text
YI Home backend is ready.
```

If this installation was upgraded from an old development build, a stale config entry may still contain an obsolete App hostname/slug. Remove only the old **YI Home** integration entry and allow current Supervisor Discovery to create a fresh setup flow.

## Frigate RTSP sensor is unavailable

The sensor is intentionally unavailable until the companion App's `8554/tcp` port has a host mapping.

Configure a free host port, restart the App, then reload this integration.

## APK import fails

APK import is handled by the companion YI RTSP App, not this integration. See the YI RTSP README for first-start and split-APK guidance:

https://github.com/Dmxsir/yi-rtsp

---

# Issues

Please report reproducible problems here:

https://github.com/Dmxsir/yi-cam-integration/issues

Include:

- Home Assistant version;
- YI Home integration version;
- YI RTSP App version;
- camera model;
- relevant logs with passwords, tokens and account credentials removed.

---

# Disclaimer

This is an independent community project and is not affiliated with or endorsed by YI Technology. YI and YI Home are trademarks of their respective owners.
