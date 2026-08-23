# Checkpoint — 2026-08-23 — Phase 6D HA OS bootstrap

## Status

- Phase 6D.1 packaging: COMPLETE.
- Local App bundle: PASS.
- HA OS Local App detected by Supervisor.
- First App start reached Supervisor but was blocked before container startup by host RTSP port collision.

## First HA OS start result

Supervisor reported:

```text
Failed to start app
Cannot start app local_yi_home because port 8554 is already in use
```

This is not a YI runtime, Docker image, AppArmor or backend failure. The host already uses TCP 8554 for the existing production go2rtc/Frigate path, which must remain untouched.

## Fix

`yi_home/config.yaml` now declares:

```yaml
ports:
  8554/tcp: null
```

The App-internal go2rtc RTSP listener remains TCP 8554. Only the default host mapping is disabled, so Supervisor no longer needs to claim host port 8554 during bootstrap.

External Frigate RTSP exposure will be added later as an optional/non-conflicting mapping rather than replacing or modifying the existing production 8554 service.

## Next gate

Regenerate the Local App bundle from the updated branch, replace `/addons/yi_home` on HA OS, reload Local Apps, rebuild/update YI Home, and start it again.

Expected next evidence:

- App container actually starts;
- backend reaches health-ready state without YI credentials;
- internal API token is created under `/data`;
- Supervisor discovery is attempted;
- no camera runtime auto-starts;
- production host port 8554 remains untouched.
