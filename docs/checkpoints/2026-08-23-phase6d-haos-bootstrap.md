# Checkpoint — 2026-08-23 — Phase 6D HA OS bootstrap

## Status

- Phase 6D.1 packaging: COMPLETE.
- Local App bundle: PASS.
- HA OS Local App detected and built by Supervisor: PASS.
- First App start without YI credentials: PASS.
- Restart/health proof: PASS.
- Secret-safe `/data` token reuse proof: PASS.
- Zero-runtime restore proof: PASS.
- **HA OS bootstrap gate: COMPLETE.**
- Next gate: Phase 6D.2 authenticated YI credential handoff.

## Host RTSP collision and fix

The first HA OS start was blocked before container startup because host TCP 8554 was already in use by the existing production go2rtc/Frigate path:

```text
Failed to start app
Cannot start app local_yi_home because port 8554 is already in use
```

This was not a YI runtime, Docker image, AppArmor or backend failure. `yi_home/config.yaml` was corrected to declare:

```yaml
ports:
  8554/tcp: null
```

The App-internal go2rtc listener remains TCP 8554 while Supervisor no longer claims host TCP 8554 by default. Existing production media services were not changed.

## First-start proof

After clearing the persisted host-port mapping, the App started under Supervisor:

```text
[03:48:56] INFO: Starting YI Home backend...
{"service":"yi-home-addon","api_version":"v1","bind":"0.0.0.0","port":8099,"authentication":"bearer","runtime_lifecycle_ready":true,"reprobe_ready":true,"media_publisher_enabled":true,"persistence_enabled":true,"initial_discovery_ok":false,"discovery_retry_enabled":true,"secrets_exposed":false}
[03:48:58] INFO: Published YI Home discovery information to Home Assistant.
[03:48:58] INFO: YI Home backend is ready.
```

`initial_discovery_ok=false` is expected because account credentials had intentionally not yet been configured.

## Restart and persistence proof

A subsequent rebuild/restart produced:

```text
[03:57:01] INFO: Backend API token reused; mode=600; value_exposed=false.
[03:57:01] INFO: Starting YI Home backend...
{"service":"yi-home-addon","api_version":"v1","bind":"0.0.0.0","port":8099,"authentication":"bearer","runtime_lifecycle_ready":true,"reprobe_ready":true,"media_publisher_enabled":true,"persistence_enabled":true,"managed_runtime_count":0,"initial_discovery_ok":false,"discovery_retry_enabled":true,"secrets_exposed":false}
[03:57:01] INFO: Published YI Home discovery information to Home Assistant.
[03:57:01] INFO: YI Home backend is ready.
```

This proves:

- `/data` persists across App rebuild/restart;
- the backend bearer token is reused and remains mode `0600`;
- the token value is not exposed;
- no camera runtime is auto-started from empty policy;
- backend health, lifecycle, reprobe, publisher and persistence layers initialize on real HA OS;
- Supervisor discovery publication succeeds;
- host production TCP 8554 remains untouched.

## Exit decision

**HA OS bootstrap is COMPLETE.** Phase 6D remains ACTIVE. Proceed to Phase 6D.2: authenticated Integration → App YI account credential handoff, secure persistence under `/data`, live account validation/discovery, and secret-safe status reporting.
