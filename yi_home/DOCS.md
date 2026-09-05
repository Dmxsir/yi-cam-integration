# YI Home App development

This App is experimental while Phase 6D is active.

## Build-context preparation

The native runtime proved during Phase 3/6 lives under the development `.analysis` tree and is intentionally not committed. Before a local App/Docker build, stage a clean context:

```bash
python3 tools/prepare_ha_app_context.py
```

The command creates `yi_home/rootfs/opt/yi-home/` containing:

- the project Python runtime modules;
- the redistributable pieces of the proven Bionic guest runtime;
- the Phase 3G native media worker artifacts;
- the proven `PPPP_CheckDevOnline` worker;
- a secret-safe runtime manifest with hashes of critical files.

It does **not** copy `libPPPP_API.so`, `.env.local`, YI credentials, backend
tokens, runtime policy or capability state. Generated `yi_home/rootfs` content
is ignored by Git. See `../docs/vendor-runtime-bootstrap.md` for the required
local vendor import flow.

Run the packaging smoke with:

```bash
PYTHON=~/Documents/yi-cam-integration/.venv/bin/python \
  bash tools/phase3_pppp_probe/run_phase6d_app_context_smoke.sh
```

Set `YI_PHASE6D_DOCKER_BUILD=1` to additionally execute a local Docker image build when Docker is available.

## Runtime layout

Inside the App image:

```text
/opt/yi-home/app/                     Python engine
/opt/yi-home/runtime/bionic-root/     proven AArch64/Bionic guest runtime
/usr/local/bin/go2rtc                 pinned managed media publisher
/data/vendor/libPPPP_API.so           private persistent vendor library
/data/                                other persistent App state
```

Before starting the backend, `/run.sh` reuses the validated private vendor
library or imports an official artifact from `/share/yi_rtsp/`. It then
generates `/data/backend-api-token` with mode 0600, starts the backend on
internal TCP 8099, and publishes Supervisor discovery service `yi_home`
containing only internal host/port/API metadata and the internal token.

YI account/camera credentials are never included in Supervisor discovery. Phase 6D.2 will add the authenticated Integration-to-App credential handoff. Until credentials are configured, the backend is expected to remain healthy with discovery pending/retrying.

RTSP is exposed on TCP 8554. The backend API is not mapped to a host port; Home Assistant Core will use the internal App network.

## Security

The initial App keeps protection enabled and does not request host networking, full access, Docker API or Home Assistant config-directory access. The custom AppArmor profile is intentionally subject to refinement during the first HA OS container run based on audit evidence.
