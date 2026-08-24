# Phase 6G checkpoint — Supervisor RTSP port discovery PASS

Date: 2026-08-24
Branch: `phase-3-linux-pppp`

## Status

Phase 6G Supervisor external RTSP port discovery is now **PASS on HA OS**.

The Integration resolves the YI RTSP App through Supervisor and reads the authoritative host mapping for container `8554/tcp`. No external RTSP port is hard-coded.

## HA OS validation evidence

Validated on the current HA OS installation with the local development App slug:

```text
external_rtsp_port: 28554
external_host: 10.0.0.16
app_slug: local_yi_home
requires_stream_enabled: true
friendly_name: ptz-front RTSP ל־Frigate
```

The generated sensor state was:

```text
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

This proves all of the following in the real HA OS environment:

- the Integration reached Supervisor successfully;
- the installed App was resolved as `local_yi_home`;
- the host-side mapping for App container `8554/tcp` was read dynamically;
- the mapped host port was `28554` in this installation;
- the LAN host was resolved as `10.0.0.16`;
- the ready-to-copy RTSP URL retained the stable-ID-based upstream stream path;
- the product does not depend on a hard-coded `28554` assumption.

## Hardening landed before validation

Commit:

```text
7b68811  Harden Phase 6G Supervisor RTSP port discovery
```

The helper now:

- exits cleanly with an unavailable export on non-Supervisor installs using Home Assistant's `is_hassio(hass)` guard;
- reads the typed `addon_info.network` field directly instead of converting the entire App-info model to a dictionary;
- therefore avoids unnecessarily materializing App `options` while resolving a non-secret port mapping;
- retains secret-safe logging only.

The current `aiohasupervisor` installed-App model was verified to expose:

```python
network: dict[str, int | None] | None
```

## Gate result

Phase 6G gates now closed:

```text
5. Supervisor/App external RTSP port + LAN host discovery: PASS
6. Ready-to-copy per-camera Frigate RTSP sensor value: PASS
```

## Frigate go2rtc export implementation

Commit:

```text
7925344  Add ready-to-copy Frigate go2rtc export
```

The existing per-camera `Frigate RTSP` sensor now also exposes:

```text
frigate_stream_name
frigate_go2rtc
```

`frigate_stream_name` is derived from the readable camera display name. If two current cameras resolve to the same slug, a short stable-ID suffix is added to keep the alias collision-safe.

`frigate_go2rtc` is a ready-to-copy YAML fragment of the form:

```yaml
go2rtc:
  streams:
    ptz_front: rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

The readable Frigate alias may change with a camera rename, but the upstream RTSP path remains stable-ID based and therefore does not change merely because the camera display name changes.

## Next validation

Deploy the updated Custom Integration to HA OS, restart Home Assistant, and confirm one or more `Frigate RTSP` sensors expose a valid `frigate_stream_name` and `frigate_go2rtc` attribute.

After that, remaining Phase 6G functional gates are:

1. Stream OFF -> corresponding external Frigate feed stops; Stream ON -> feed returns.
2. Frigate detection works on the App-owned source.
3. Frigate recording works on the App-owned source.
4. Audio handling/recording is correct where enabled.
5. Final secret-redaction/export review.

## Architecture remains unchanged

```text
YI camera
  -> YI RTSP App runtime
  -> App-owned go2rtc RTSP publication
  -> Supervisor host-port mapping
  -> external Frigate
```

Frigate remains an optional consumer and does not own or start the YI camera runtime.
