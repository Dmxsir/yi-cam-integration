# YI TNP cross-check and Phase 2C live boundary

## Evidence labels

This document uses only the requested labels:

- `APK_PROVEN`: recovered from the 2022 YI Home Android APK.
- `LIVE_CLOUD_PROVEN`: observed through current production YI cloud APIs.
- `YI_DEVICE_SOURCE_CORROBORATED`: present in public Yi device-side source.
- `THIRD_PARTY_PPPP_REFERENCE`: behavior from a generic PPPP project or research source.
- `LIVE_CAMERA_PROVEN`: observed in the controlled production y291ga session.
- `UNKNOWN`: not established by the evidence available here.

Static agreement is not promoted to live proof. In particular, the PPPP
transport/message variant and the TNP application version remain separate.

## Public-source scope

| Source | Relevant use | Reuse status |
|---|---|---|
| [`frankzhangshcn/p2p_tnp`](https://github.com/frankzhangshcn/p2p_tnp) | Yi device-side TNP channels, command authentication, video headers, encryption, and SPS/PPS/VPS handling | No license file was present when reviewed. Evidence only; do not copy or redistribute. |
| [`devbis/aiopppp`](https://github.com/devbis/aiopppp) | Generic PPPP discovery/session concepts for A9/X5-style cameras | Apache-2.0, but neither its device commands nor its compatibility with Yi's fork is established. |
| [`DavidVentura/cam-reverse`](https://github.com/DavidVentura/cam-reverse) | Reverse-engineering method: static analysis, dynamic observation, and packet reconstruction | Methodology/reference only. Its X5/A9 application protocol is not Yi TNP. |
| [`magicus/pppp-dissector`](https://github.com/magicus/pppp-dissector) | Generic PPPP packet vocabulary and Wireshark inspection | MIT; useful after a secret-safe transport capture exists, not proof of Yi framing. |
| [`roleoroleo/yi-hack-Allwinner-v2`](https://github.com/roleoroleo/yi-hack-Allwinner-v2) | Hardware corroboration for y291ga / firmware families | MIT; model corroboration only. No modified firmware was used. |
| [Almost Secure PPPP overview](https://palant.info/2025/11/05/an-overview-of-the-pppp-protocol-for-iot-cameras/) | Recent comparison of generic PPPP and the substantially different Yi fork | `THIRD_PARTY_PPPP_REFERENCE`; its F1/F2 terminology is not TNP application versioning. |
| [Cisco Talos TALOS-2018-0616](https://www.talosintelligence.com/vulnerability_reports/TALOS-2018-0616) | Independent identification of Yi's `p2p_tnp` service and video-specific cryptography | Older-firmware corroboration, not a current y291ga wire contract. |

The public Yi repository exposes `p2p_tnp.c` but no explicit license. Nothing
from it was incorporated into the oracle implementation; it was used only to
compare independently recovered APK behavior.

## Oracle selection

No legitimate local YI Windows installation or `PPPP_API.dll` was found in the
scoped Program Files locations. The selected oracle was therefore the APK's
untouched `arm64-v8a/libPPPP_API.so`:

```text
format:  ELF64 AArch64 Android
size:    243576 bytes
SHA-256: 83FEED8079AA6E6E955DEBA13640FB8658AAB3DB8CFCD0B8BF74201F087D729C
```

It ran in an official Android 15 Google APIs x86_64 emulator whose ABI list
included `arm64-v8a`. Android's translation layer loaded the library without a
patch. The library remains an oracle, not a distributable production
dependency.

## Behavior cross-check

| Behavior | APK client evidence | Public Yi device-side evidence | Live production evidence | Conclusion | Confidence |
|---|---|---|---|---|---|
| Channel 0 = IOCTRL | `TnpCamera` writes and reads command units on channel 0. | `CHANNEL_IOCTRL = 0`; `myDoIOCtrl` parses the 40-byte command header. | The native oracle wrote 56 bytes on channel 0, then attempted an 8-byte channel-0 read. No response bytes arrived. | Channel assignment is `APK_PROVEN` and `YI_DEVICE_SOURCE_CORROBORATED`; receipt/parsing by this camera is `UNKNOWN`. | High static; no live peer payload. |
| Channel 1 = audio | The APK's audio worker reads channel 1. | `CHANNEL_AUDIO` follows channel 0 and the audio sender selects it. | Not read in this phase. | `APK_PROVEN`, `YI_DEVICE_SOURCE_CORROBORATED`; not live-proven. | High static. |
| Channel 2 = realtime I-frame | The realtime-I worker reads channel 2 and applies I-frame decryption. | `CHANNEL_VIDEO_REALTIME_IFRAME = 2`; realtime I-frames select it. | Zero units received. | `APK_PROVEN`, `YI_DEVICE_SOURCE_CORROBORATED`; `LIVE_CAMERA_PROVEN` is not reached. | High static. |
| Channel 3 = realtime P-frame | The realtime-P worker reads channel 3. | `CHANNEL_VIDEO_REALTIME_PFRAME = 3`; non-I realtime frames select it. | Zero units received. | `APK_PROVEN`, `YI_DEVICE_SOURCE_CORROBORATED`; `LIVE_CAMERA_PROVEN` is not reached. | High static. |
| Channel 4 = recorded I-frame | The playback-I worker reads channel 4. | `CHANNEL_VIDEO_RECORD_IFRAME = 4`. | Not read. | Static agreement only. | High static. |
| Channel 5 = recorded P-frame | The playback-P worker reads channel 5. | `CHANNEL_VIDEO_RECORD_PFRAME = 5`. | Not read. | Static agreement only. | High static. |
| TNP outer header = 8 bytes | `TNPHead.LEN_HEAD = 8`. | `st_AVStreamIOHead` precedes command and media records. | The client requested 8 response bytes, but the remote closed with zero bytes delivered. | `APK_PROVEN` and corroborated; live inbound size is `UNKNOWN`. | High static. |
| IOCTRL header = 40 bytes | `TNPIOCtrlHead.LEN_HEAD = 40`; big-endian for type-2 devices. | `st_AVIOCtrlHead` is parsed with network-order 16/32-bit fields. | The outgoing set-resolution unit was 8 + 40 + 8 = 56 bytes and native `PPPP_Write` returned 56. This proves the oracle call, not camera parsing. | `APK_PROVEN`, `YI_DEVICE_SOURCE_CORROBORATED`; peer acceptance is `UNKNOWN`. | High static. |
| Video frame header = 24 bytes | `TNPFrameHead` and `AVFrame` use 24 bytes after `TNPHead`. | `FRAMEINFO_t` carries codec, flags, dimensions, sequence, and timestamps. | No video unit received. | Static agreement only. | High static. |
| Command authentication | For encrypted devices: 7-character session prefix + 8-character per-command suffix; HMAC-SHA1 keyed by camera password over `user=xiaoyiuser&nonce=<15 chars>`; first 15 Base64 characters. `PPPP_SendLogin` is unused. | `do_auth` applies the same nonce split, replay checks, HMAC-SHA1, and 15-byte comparison. | The first authenticated command was written, then the peer closed after about 11 seconds without an auth response. | Algorithm is `APK_PROVEN` and `YI_DEVICE_SOURCE_CORROBORATED`. Current-camera authentication is not proven; the close does not distinguish auth rejection from an unparsed/unsupported command unit. | High static; live result unresolved. |
| TNP application version | `tnpHeaderVersion=0` means detect; client first sends version 2 and adopts the first response's version if different. | Device source has a per-session `tnp_ver` and a `TNP_VERSION_2` default. | The oracle sent version 2. No peer TNP header was received. | Observed peer version is `UNKNOWN`. A client-sent provisional value is not live peer proof. | High distinction; unknown value. |
| PPPP transport header variant | Hidden inside the proprietary native library. | Not exposed by the TNP application source. | No secret-safe packet capture was made. | `UNKNOWN`; it must not be inferred from TNP version 2. | Unknown. |
| Realtime start | `IOTYPE_USER_IPCAM_TNP_START_REALTIME = 9029` on channel 0. | `IOTYPE_USER_TNP_IPCAM_START_KEY` consumes the four-byte start structure and enables live video. | Not sent because authentication never completed. | Command and structure are statically established; live execution failed before this point. | High static; no live proof. |
| I-frame encryption | APK key is `camera_password + "0"`; decrypt exactly payload `[4:20]` and `[20:36]` as independent AES blocks. | Device source resets AES with a null IV before encrypting each 16-byte block at offsets 4 and 20. For a single block, this is equivalent to AES-128 ECB/NoPadding. | No encrypted I-frame received. | `APK_PROVEN`, `YI_DEVICE_SOURCE_CORROBORATED`; live decryption remains unproven. | High static. |
| SPS/PPS/VPS handling | Client forwards the compressed payload and does not synthesize parameter sets. | Device caches VPS/SPS/PPS and prepends the available sets to an IDR before channel-2 transmission. | No I-frame received. | Device behavior is corroborated, but y291ga codec and repetition behavior are `UNKNOWN`. | Medium until live frames. |

## Exact official realtime start payload

The APK's fresh-player path reads `CAMERA_PLAYER_HD` with default `-1`. A
missing preference selects resolution `2`. `setResolution(2)` increments the
use count from 0 to 1 and queues command 4881 with two big-endian 32-bit values:

```text
offset 0..3: resolution = 2
offset 4..7: usecount   = 1
```

`startPlay()` then reaches `AntsCameraTnp.doGoLive()`, increments the use count
to 2, and serializes command 9029 (`0x2345`) as:

| Offset | Value | Meaning | Evidence |
|---:|---:|---|---|
| 0 | `2` | usecount | APK fresh-player call sequence |
| 1 | `2` | resolution | APK default preference branch |
| 2 | `1` | command version | literal argument to `SMsgAVIoctrlTnpPlay.parseContent` |
| 3 | `0` | reserved | serializer literal |

The payload is four single-byte fields, so it has no multi-byte endian
question. The containing TNP and IOCTRL length/type fields are big-endian for a
type-2 device. The controlled run did **not** send 9029 because it did not
receive a successful authenticated response to the prerequisite command.

## Controlled live result

Immediately before each native attempt, the coordinator performed a fresh
EU/IL login, device discovery, selection, and `/v4/tnp/device_info` fetch. The
approved primary camera was online and still matched model `83`, normalized
`y291ga`, type `2`. DID, InitString, the first license component, and recovered
camera password were all available in memory; `p2p_encrypt` was true. Values
were never printed or persisted.

The first attempt returned APK-defined `-3003` (`ERROR_PPPP_TIME_OUT`). A
separate emulator connectivity check showed that this emulator process had no
external route, so this attempt is classified as an infrastructure transient,
not a camera result.

The one permitted retry used a network-enabled emulator and produced:

| Step | Sanitized observation | Evidence |
|---|---|---|
| `PPPP_Initialize` | return `0`; max sessions 12 | Live native-oracle observation; not camera traffic |
| `PPPP_GetAPIVersion` | `0xA2030401` | Live native-oracle observation |
| `PPPP_Connect` | direct-policy flag `0x4B`; return/session handle `1`; about 333 ms | `LIVE_CAMERA_PROVEN` |
| `PPPP_Check` | return `0`; mode `0`; connect 334 ms; P2P 306 ms; relay 0 ms | `LIVE_CAMERA_PROVEN`: direct P2P mode |
| `PPPP_Write` | channel 0, command 4881, command number 1, TNP client version 2, buffer 56, return 56 | Live native API observation; peer parsing remains unknown |
| `PPPP_Read` | requested 8-byte channel-0 header; after about 11.0 s returned `-3012`, actual length 0 | `LIVE_CAMERA_PROVEN`: remote session closure before a TNP response |

No response header, auth result, command 9029, video frame, or normal
application-level stop sequence was observed. The coordinator force-stopped
the isolated app after socket termination, and the Android exit record showed
only that requested force-stop. No third native connection was attempted.

## Discrepancies and unresolved boundary

| Topic | APK client | Public Yi device-side source | Actual production y291ga |
|---|---|---|---|
| PPPP establishment | Direct `PPPP_Connect` with flag `0x4B`, then `PPPP_Check` | Uses a PPPP session handle and channel multiplexer | MATCH: session handle 1, check mode 0/P2P |
| First TNP command | Version-2 8-byte outer header + 40-byte authenticated header + payload | Parses that structure and normally sends an auth/result response | DIFFERENT/UNKNOWN: native write succeeded, but the camera delivered no response and closed remotely |
| Failed authentication behavior | Client expects an auth result in the response header | Public source sends an auth result for bad nonce/password/version | UNKNOWN: no response bytes, so an auth result was not observable |
| Realtime start/video | APK sends 9029, then reads channels 2 and 3 | Public source enables video and emits I/P frames on 2/3 | NOT REACHED |
| I-frame encryption and parameter sets | Client decrypts two blocks and forwards payload | Source encrypts two blocks and prepends cached parameter sets to IDR | NOT REACHED |

The evidence does **not** prove that the cloud-recovered password is wrong, nor
that version 2 is unsupported. It proves only that this minimal oracle's first
TNP command did not yield an observable application response before the
production y291ga closed the session. Distinguishing password/auth rejection,
header-version negotiation, timing, and another missing official-client state
is the remaining Phase 2C boundary.
