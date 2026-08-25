# Phase 6G checkpoint — Frigate RTSP export

Date: 2026-08-25

## Status

Phase 6G is **COMPLETE**.

The final external Frigate path is validated end-to-end on the real Home Assistant OS / Proxmox installation:

```text
YI camera
  -> YI RTSP App runtime
  -> App-owned go2rtc / RTSP publication
  -> Home Assistant OS host port mapping
  -> external Frigate host
  -> Frigate go2rtc
  -> live view / detection / recording / audio
```

Frigate remains an optional consumer. YI RTSP owns camera runtime and media publication; YI Camera Connect owns Home Assistant discovery/entities/export UX.

## Stable stream identity

The upstream media path uses the secret-safe stable camera identity rather than the user-visible camera name:

```text
rtsp://<HA-host>:<mapped-RTSP-port>/yi_<stable-prefix>
```

Camera renames do not alter the upstream RTSP path. A readable Frigate alias is generated separately from the current display name and duplicate readable names receive a short stable-ID suffix.

## HA OS Supervisor discovery — PASS

Validated result for `ptz-front`:

```text
external_rtsp_port: 28554
external_host: 10.0.0.16
app_slug: local_yi_home
requires_stream_enabled: true
rtsp://10.0.0.16:28554/yi_e2f22804fecd
```

This proves that the Integration resolves the current Supervisor mapping for App container port `8554/tcp`; `28554` is installation-specific and is not hard-coded.

Implementation behavior:

- Config Flow persists the real Supervisor App slug from discovery.
- Older entries recover the originating App slug from Supervisor discovery with compatibility fallbacks.
- Integration setup reads `addon_info.network` directly and extracts the host mapping for `8554/tcp`.
- The LAN host prefers Supervisor primary IPv4, with Home Assistant internal URL/local API IP fallbacks.
- Non-Supervised Home Assistant returns the external export as unavailable cleanly.
- The App's full options payload is not materialized just to discover the RTSP mapping.

## Generated Frigate export — PASS

Each camera exposes a ready-to-copy `Frigate RTSP` sensor.

The generated Frigate stream alias is readable and collision-safe. The generated `go2rtc` YAML now includes both the original App-owned RTSP source and an Opus audio producer for Frigate live audio:

```yaml
go2rtc:
  streams:
    ptz_front:
      - rtsp://10.0.0.16:28554/yi_e2f22804fecd
      - "ffmpeg:ptz_front#audio=opus"
```

The upstream YI RTSP source remains H264 + AAC. Opus is only the Frigate/go2rtc live-view compatibility layer; it does not change the App-owned source.

For recording, Frigate was validated with `record` on the restream input and `preset-record-generic-audio-copy`, preserving the AAC track without unnecessary transcoding.

## Stream OFF / ON ownership validation — PASS

Controlled validation used `ptz-front`:

1. Frigate displayed live video from the App-owned source.
2. Turning the YI Camera Connect `Stream` switch OFF moved runtime to `STOPPED`.
3. The corresponding Frigate feed stopped.
4. Turning the switch ON restarted the App-owned runtime.
5. Frigate recovered the same feed automatically without restart or URL/YAML changes.
6. Recovery took roughly one minute on the tested installation.

This proves there is no active legacy development publisher dependency in the Frigate path.

## Detection — PASS

A real person/motion pass in front of the camera produced Frigate detection/events through the App-owned RTSP source.

## Recording — PASS

Frigate created playable recordings from the same App-owned RTSP source.

## Audio — PASS

The App-owned RTSP transport exposes AAC audio and Frigate go2rtc receives it. Live audio compatibility was completed by adding an Opus producer in the Frigate `go2rtc` stream definition. Recording audio uses AAC copy.

Final user validation confirmed sound is working on all tested/migrated YI cameras in Frigate.

During debugging, `yi_pool` and `yi_warehouse` both showed H264 + AAC input and an Opus producer inside Frigate/go2rtc. A temporary low measured level on `yi_warehouse` was source-level behavior, not loss of the audio track in the YI RTSP transport.

## Secret-safe export/diagnostic review — PASS

The Phase 6G export path does not expose YI account credentials, cloud UID/DID values, App bearer tokens, or media credentials.

User-facing Frigate sensor/export data is limited to:

- LAN host;
- mapped RTSP port;
- secret-safe App slug;
- readable Frigate alias;
- stable-ID-based RTSP path;
- generated go2rtc YAML;
- `requires_stream_enabled` policy metadata.

The Supervisor resolver logs only the selected App slug plus boolean host/port availability. Integration setup logs only boolean resolution state. It does not log App options or the bearer token.

The coordinator also rejects camera inventory unless the App explicitly returns `secrets_exposed: false`, preserving the existing secret-safe API contract.

## Phase 6G gate status

1. Stream OFF -> Frigate feed stops; ON -> feed returns: **PASS**.
2. Frigate detect on the new App-owned source: **PASS**.
3. Frigate recording on the new App-owned source: **PASS**.
4. Audio handling/recording: **PASS**.
5. HA OS external RTSP host/port discovery: **PASS**.
6. HA OS per-camera ready-to-copy RTSP sensor: **PASS**.
7. Generated Frigate `go2rtc` export/snippet UX: **PASS**.
8. Secret-safe export/diagnostic review: **PASS**.

**Phase 6G exit gate: PASS.**

## Follow-up / next work

Phase 6G no longer blocks the product path. Follow-up work belongs to the remaining Home Assistant product/release phases rather than Frigate media interoperability:

- finish Phase 6E polish (diagnostics/reauth, removed-camera cleanup, redaction regression coverage);
- Phase 6F zero-manual-config onboarding polish;
- compatibility-sensitive public naming/repository split;
- release/distribution automation;
- optional later improvements such as recovery-latency tuning.

## Naming

Selected eventual public product names remain:

```text
App:          YI RTSP
Integration:  YI Camera Connect
```

Current internal `yi_home` identifiers remain unchanged until the explicit compatibility-sensitive rename/repository-split migration.
