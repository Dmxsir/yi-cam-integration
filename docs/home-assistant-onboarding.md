# Home Assistant onboarding contract

This document locks the intended v1 user experience and the responsibility
boundary between the YI Home App (formerly add-on) and the YI Home custom
Integration.

## Installation order

The supported v1 order is:

```text
1. Install YI Home App
2. Start YI Home App
3. Add YI Home Integration
4. Enter YI Home account credentials in the Integration config flow
5. Integration sends credentials to the App over the authenticated internal API
6. App logs in to YI Home and discovers the account cameras
7. Integration reads the secret-safe inventory from the App
8. Home Assistant creates Devices and Entities
9. App owns PPPP/TNP sessions, media publication and self-healing
```

The App is installed first because it is the engine that contains the native
runtime, QEMU/libPPPP worker, FFmpeg and managed go2rtc publisher. The custom
Integration intentionally does not carry or execute those native components.

If the Integration is added before the App is available, its config flow should
show a clear `App not found` / `Install YI Home App first` result rather than
asking the user for low-level host, port, UID, DID or RTSP information.

## App discovery and internal authentication

On first start the App will:

1. generate a strong random internal backend API token;
2. persist that token under `/data` with restrictive permissions;
3. publish its internal host, port, API version and API credential through
   Supervisor App discovery;
4. never expose that backend API port on the host unless a future feature has a
   specific requirement.

The Integration receives this connection metadata through its
`async_step_hassio` config-flow path. The user never types or manages the
internal API token.

The backend API token authenticates only Home Assistant Integration <-> App
communication. It is not a YI account or camera credential.

## YI account credential flow

The normal user-facing config flow is:

```text
YI Home Integration
  -> account / email
  -> password
  -> region/country if required
  -> Connect
```

The Integration sends those credentials only to the already-discovered App over
its authenticated internal API.

The App then owns YI authentication and account discovery:

```text
Integration UI
   |
   | authenticated internal API
   v
YI Home App
   |
   +--> YI account login
   +--> camera discovery
   +--> capability cache
   +--> PPPP/TNP runtime
   +--> RTSP publication
```

## Secret ownership

Target v1 policy:

- YI account credentials are entered through the Home Assistant Integration UI.
- The Integration should avoid retaining the YI account password in its config
  entry when long-term storage there is not required.
- The App persists the credentials it needs under protected `/data` storage with
  restrictive file permissions.
- YI credentials are never included in Supervisor discovery payloads.
- YI credentials are never returned by read APIs, diagnostics or camera state.
- YI credentials are never printed in logs.
- Camera UID/DID, camera passwords, PPPP/TNP connection material, tokens,
  licenses and InitString values remain secret-bearing backend data and are not
  exposed to the Integration.

If YI authentication later becomes invalid, the App reports a secret-safe
`reauth_required` state. The Integration starts a Home Assistant reauthentication
flow, asks the user for fresh YI credentials, and sends the replacement to the
App. Reinstalling the App should not be required.

## Synchronization model

The App is the source of truth for camera/runtime state. The Integration does
not independently log in to YI cloud or open camera sessions.

The Integration synchronizes secret-safe data from the App, including:

- discovered camera list;
- stable camera identity (`stable_id`);
- friendly camera name;
- online/runtime state;
- capability state;
- stable media endpoint metadata;
- restart/reprobe status and diagnostics.

Home Assistant Devices are keyed by immutable `stable_id`, so a camera rename in
YI Home does not create a new Home Assistant device or change the stable RTSP
identity.

## User experience target

The completed flow should feel like:

```text
Install YI Home App
        |
        v
Add Integration -> YI Home
        |
        v
App found automatically
        |
        v
Enter YI Home login
        |
        v
Found 7 cameras
        |
        v
Finish
```

The user must not need to configure:

- UID / DID;
- raw camera model;
- TNP version;
- camera password;
- RTSP URL;
- go2rtc YAML;
- Frigate YAML for core Home Assistant use;
- QEMU/native runtime paths.

Frigate remains an optional consumer of the App-owned stable RTSP endpoints.
