# Home Assistant App (Add-on) Requirements

This document records the current official Home Assistant requirements and the
packaging decisions they imply for the YI Home engine.

Home Assistant's 2026 developer documentation calls these containers **Apps**
(formerly **add-ons**). The project may continue to use the user-facing name
"YI Home Add-on" during development, but packaging must follow the current App
specification.

Official references reviewed in August 2026:

- https://developers.home-assistant.io/docs/apps/
- https://developers.home-assistant.io/docs/apps/tutorial/
- https://developers.home-assistant.io/docs/apps/configuration/
- https://developers.home-assistant.io/docs/apps/communication/
- https://developers.home-assistant.io/docs/apps/security/
- https://developers.home-assistant.io/docs/apps/presentation/
- https://developers.home-assistant.io/docs/apps/testing/
- https://developers.home-assistant.io/docs/apps/publishing/
- https://developers.home-assistant.io/docs/apps/repository/
- https://developers.home-assistant.io/docs/core/integration/config_flow/

Reference implementation reviewed:

- Home Assistant official Mosquitto App discovery scripts in
  `home-assistant/addons`.

## 1. Repository layout

A distributable Home Assistant App repository requires `repository.yaml` at the
repository root. Each App lives in its own unique folder.

Target layout for this project:

```text
repository.yaml

yi_home/
  config.yaml
  Dockerfile
  run.sh
  apparmor.txt
  DOCS.md
  README.md
  CHANGELOG.md
  translations/
    en.yaml
  icon.png
  logo.png
```

`build.yaml` is optional and depends on the final multi-architecture build
strategy.

For initial local HA OS testing the App may instead be copied into `/addons` and
will appear in the Local Apps repository.

## 2. Required `config.yaml` fields

Current Home Assistant documentation requires:

- `name`
- `version`
- `slug`
- `description`
- `arch`

Current documented architectures are `amd64` and `aarch64`. We must advertise
only architectures on which the full native runtime has actually been tested.

Initial project direction:

```yaml
name: "YI Home"
version: "0.1.0"
slug: "yi_home"
description: "Native YI Home camera runtime for Home Assistant"
arch:
  - amd64
startup: application
boot: auto
init: false
stage: experimental
```

`amd64` is the first packaging target. `aarch64` must not be declared until the
QEMU/native-library/runtime path is verified there.

## 3. Docker image requirements

The App is a normal container image managed by Supervisor.

Important current rule: since Supervisor 2026.04.0, `BUILD_FROM` is no longer
implicitly supplied when `build.yaml` is absent. The Dockerfile must use an
explicit `FROM` image. Home Assistant recommends pinning the base image version
for reproducible builds rather than relying indefinitely on `latest`.

The container must include all runtime dependencies required by the engine:

- Python runtime and project backend
- QEMU user-mode runtime if still required
- `libPPPP_API.so` and the native worker
- FFmpeg / ffprobe
- managed media publisher (go2rtc or the selected replacement)

No runtime path may depend on the development checkout under a user's home
directory.

If images are published rather than built locally, pre-built registry images
are the preferred Home Assistant distribution method. Home Assistant provides
GitHub Actions builder workflows and supports signed images.

## 4. Persistent data

`/data` is the App's persistent storage volume. `/data/options.json` contains
Supervisor-managed App options.

YI Home must move persistent backend state to `/data`, including:

```text
/data/capabilities.json
/data/runtime-state.json
/data/logs/                 # only if persistent logs are intentionally kept
/data/backend-api-token     # generated internal Integration/App credential
```

Temporary probe media and transient process data should remain outside the
persistent state or be cleaned automatically.

The App does **not** need access to the Home Assistant configuration directory.
Do not map `homeassistant_config`, `config`, or `share` unless a future feature
has a concrete requirement.

If user-visible files are ever required, Home Assistant recommends
`addon_config` instead of mapping the complete Home Assistant config directory.

## 5. Network design

Home Assistant Core and Apps share an internal network and can communicate using
App names/aliases. An App name is based on `{REPO}_{SLUG}`; its DNS form replaces
underscores with hyphens.

Target YI Home network design:

- Backend API listens inside the App network, not on host networking.
- `host_network: false`.
- No host exposure is required for the backend API used by the custom
  Integration.
- The Integration discovers the App through Supervisor/App discovery and then
  talks to its internal address.
- RTSP port `8554/tcp` may be exposed to the host when external consumers such
  as a non-Supervisor Frigate instance need it.
- Home Assistant/other Supervisor Apps should prefer the internal App network.

The backend must not assume `127.0.0.1` once packaged; Home Assistant Core is a
separate container. The service will need to bind to the App interface
(`0.0.0.0` inside the container) while keeping the API inaccessible from the
host unless explicitly mapped.

## 6. Integration discovery and internal API authentication

Home Assistant supports discovery from an App. Config flows reserve
`async_step_hassio` specifically for a flow triggered by Supervisor App
(formerly add-on) discovery.

This is the preferred direction for YI Home:

```text
YI Home App starts
  -> creates/loads a random backend API credential under /data
  -> publishes Supervisor discovery information
  -> Home Assistant starts/updates the YI Home config flow
  -> Integration receives internal host/port/API credential
  -> Integration validates backend API version/health
  -> user confirms/configures account
```

The official Mosquitto App demonstrates this pattern: it creates a random
Home-Assistant-only password, persists it under `/data/system_user.json`, and
publishes `host`, `port`, `username` and `password` through
`bashio::discovery`. This gives us a supported pattern for authenticating the
YI Home Integration to the backend without a user-managed token and without
exposing the backend API on the host.

YI Home decision:

- generate a strong random backend API token on first App start;
- persist it mode `0600` under `/data`;
- backend listens on the internal App network;
- publish `host`, `port`, API version and the internal API token using
  Supervisor discovery;
- Integration consumes the discovery in `async_step_hassio`;
- never print the token in normal logs or diagnostics;
- rotation/recovery behavior will be defined during 6D/6E.

This internal API credential is not a YI camera/account credential. YI camera
passwords, tokens, PPPP material, UID/DID secrets and account credentials must
never be sent in the discovery payload.

A stable Integration config-entry unique ID must be used to prevent duplicate
setup flows.

## 7. YI account credentials

`options` and `schema` in `config.yaml` define Supervisor-managed App settings.
Supervisor treats App options as potentially secret-bearing and redacts them
from most API clients.

However, the product target remains that the user should configure the YI
account through the Home Assistant Integration rather than manually editing App
options.

The secure YI credential handoff from Integration -> App must satisfy:

- send credentials only over the authenticated internal backend API;
- never place YI credentials in Supervisor discovery payloads;
- never return them through backend read APIs or diagnostics;
- never log them;
- persist them only in Home Assistant/Supervisor-controlled storage;
- use restrictive file permissions if the App keeps its own `/data` credential
  record;
- support reauthentication without reinstalling the App.

Current Supervisor APIs expose a concept of `system_managed` Apps tied to a Home
Assistant config entry, but Home Assistant Core support is still evolving in
2026. Therefore the project must not depend on undocumented/internal management
APIs until they are verified as supported for custom integrations.

A practical v1 design is therefore:

```text
Supervisor discovery -> internal API token -> Integration
Integration config flow -> YI account credentials
Integration -> authenticated internal API -> App
App -> restrictive persistent credential store under /data
```

This preserves the desired zero-terminal user experience without depending on
unfinished system-managed App support.

## 8. Security requirements

Home Assistant's security guidance aligns well with this project. Target:

- keep protection mode enabled;
- `host_network: false`;
- no `full_access`;
- no Docker API;
- no host PID namespace;
- no unnecessary privileged capabilities;
- no Home Assistant config-directory mapping;
- provide a custom `apparmor.txt` once runtime filesystem/process requirements
  are known;
- expose the minimum ports only;
- sign published images when release automation is added.

QEMU, FFmpeg and the native PPPP worker do not by themselves require host
privileges. Packaging should preserve that property.

## 9. Ingress

Ingress is useful only if we later provide a human-facing web UI for diagnostics
or management. It is **not required** for the Integration-to-backend API.

If enabled later:

- set `ingress: true`;
- default ingress port is 8099 unless configured otherwise;
- ingress requests come through Supervisor and are already authenticated;
- Home Assistant documentation requires an ingress web server to accept only
  the Supervisor ingress proxy source (`172.30.32.2`) for that interface.

For the first product version, the normal Home Assistant Integration UI should
be sufficient; a separate App web UI is optional.

## 10. Startup, watchdog and health

This engine is a long-running application, so `startup: application` is the
appropriate initial choice.

The App should expose a Supervisor watchdog URL mapped to the existing backend
health endpoint once packaging is implemented, conceptually:

```yaml
watchdog: "http://[HOST]:[PORT:8099]/api/v1/health"
```

The exact internal port is finalized in 6D.

Backend `/health` must distinguish:

- process alive / API responsive;
- cloud discovery status;
- runtime lifecycle availability;
- media publisher availability;
- per-camera failures without declaring the entire App dead.

## 11. Backup behavior

Capability cache and non-secret runtime preferences under `/data` should be
included in normal App backups.

Camera cloud credentials must use the chosen Home Assistant/App persistent
storage mechanism and remain restorable without appearing in diagnostics.

A `cold` backup is not currently required; the engine should be designed so a
normal backup can capture persistent state without depending on active camera
sessions.

## 12. Local development/testing

Home Assistant currently recommends its App devcontainer for local development,
which runs Supervisor + Home Assistant and exposes repository Apps as Local
Apps.

For hardware/network behavior that must be tested on the real HA OS host, Apps
can be placed under `/addons/<app-folder>` via SSH/Samba and rebuilt locally.
When testing a local build, do not set an `image:` value that would cause
Supervisor to download a published image instead.

Project test sequence for Phase 6D:

```text
1. Build amd64 App locally.
2. Install as Local App on HA OS.
3. Validate /data persistence.
4. Validate generated internal API credential + Supervisor discovery.
5. Validate YI cloud discovery from the container.
6. Validate native PPPP/TNP runtime in the container.
7. Validate two simultaneous camera streams.
8. Validate App restart and Supervisor watchdog behavior.
9. Validate App -> Integration async_step_hassio discovery.
10. Validate no host privileges/config mappings are required.
```

## 13. Phase 6D packaging gate for this project

Phase 6D cannot be considered complete until all of the following are true:

- valid `repository.yaml` and App `config.yaml`;
- explicit reproducible Docker base image;
- full runtime packaged without development-machine paths;
- `/data` capability/runtime persistence;
- generated internal backend API credential persists safely under `/data`;
- Supervisor discovery supplies the Integration with internal connection data;
- protected mode remains enabled;
- no host network/full access/Docker API requirements;
- backend API reachable from Home Assistant Core through the internal network;
- App discovery can trigger the YI Home Integration `hassio` config-flow path;
- RTSP publication works from the packaged container;
- at least two cameras operate concurrently;
- restart/self-healing works after Supervisor restarts the App;
- secrets do not appear in App logs, backend read APIs or diagnostics;
- YI credentials never appear in Supervisor discovery payloads.
