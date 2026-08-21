# TNP wire protocol recovered from the APK

This is the application framing carried over PPPP channels by `TnpCamera`.
Multi-byte fields are big-endian for type-2 cameras because
`AntsCamera.isByteOrderBig()` returns true. Sizes and offsets below are exact
for the inspected APK.

## PPPP channel allocation

| Channel | Direction / worker | Content |
|---:|---|---|
| 0 | bidirectional | TNP IO-control commands and responses |
| 1 | bidirectional | received and sent audio |
| 2 | receive | realtime I frames |
| 3 | receive | realtime P frames |
| 4 | receive | playback/record I frames |
| 5 | receive | playback/record P frames |

Each receive worker first requests an 8-byte outer header with
`PPPP_Read(handle, channel, ..., timeout=-1)`, parses its declared `dataSize`,
then reads that many payload bytes from the same channel.

## `TNPHead` — 8 bytes

| Offset | Size | Field | Meaning |
|---:|---:|---|---|
| 0 | 1 | `version` | TNP header version |
| 1 | 1 | `ioType` | `1` video, `2` audio, `3` command |
| 2 | 2 | reserved | zero in generated headers |
| 4 | 4 | `dataSize` | bytes following this header |

There is no magic value in this eight-byte structure.

### Header-version detection

Cloud metadata does not supply a header version. `DeviceInfo.c()` passes zero;
`TnpCamera` interprets that as “detect,” starts provisionally with version 2,
and sends the first queued command with that version. When the first command
response arrives, a different response-header version is saved, the response
is suppressed, and the original command is resent with the detected version.
The actual value used by the production `y21ga` remains **UNKNOWN** because no
PPPP session was opened.

## `TNPFrameHead` — 24 bytes

The payload on video channels begins with this structure:

| Offset | Size | Field | Observed interpretation |
|---:|---:|---|---|
| 0 | 2 | `codec_id` | codec discriminator |
| 2 | 1 | `flags` | bit 0 is treated by `AVFrame` as I-frame |
| 3 | 1 | `liveFlag` | bit 0: live/playback; bit 1: privacy |
| 4 | 1 | `onlineNum` | online viewer count |
| 5 | 1 | `useCount` | stream-generation counter |
| 6 | 2 | `seq` | frame sequence number |
| 8 | 2 | `width` | encoded width |
| 10 | 2 | `height` | encoded height |
| 12 | 4 | `timestamp` | seconds timestamp |
| 16 | 1 | `isDay` | day/night flag |
| 17 | 1 | `ref` / `cover_state` | context-dependent byte |
| 18 | 1 | `outloss` | loss metric |
| 19 | 1 | `inloss` | loss metric |
| 20 | 4 | `timestamp_ms` | millisecond component/value |

The compressed media immediately follows at offset 24 within the TNP video
payload, or offset 32 when counting the outer `TNPHead` from the PPPP wire read.

`AVFrame` uses codec IDs `78` for H.264 and `81` for H.265. A legacy constant
`TNP_Proto.CODECID_V_H264=3` conflicts with the active `AVFrame` parser and is
not used to classify received frames; it must not be used for a bridge.

## `TNPIOCtrlHead` — 40 bytes

| Offset | Size | Request field | Response interpretation |
|---:|---:|---|---|
| 0 | 2 | command type | command type |
| 2 | 2 | command number | correlates queued request/response |
| 4 | 2 | extra-header size | extra-header size; generated requests use 0 |
| 6 | 2 | command-data size | response-data size |
| 8 | 32 | zero-padded `account,password` bytes | first four bytes parsed as auth result; remaining bytes reserved/contextual |

An IO-control write is:

```text
TNPHead(version, ioType=3, dataSize=40+payloadSize)
TNPIOCtrlHead(command, commandNumber, 0, payloadSize, authInfo)
command payload
```

The entire `8 + 40 + payloadSize` buffer is written to PPPP channel 0.

Known parsed authentication results are:

| Result | APK behavior |
|---:|---|
| 0 | authentication succeeded |
| 1 or 2 | account/password error |
| 4 | command is eligible for authentication retry |

Exact device semantics for all other result integers are **UNKNOWN**.

## Command authentication

The raw cloud token, token secret, TNP license value, and license device key are
not placed in `TNPIOCtrlHead`.

When `p2p_encrypt` is false:

```text
account  = "admin"
password = recovered camera password
authInfo = ASCII(account + "," + password), zero-padded to 32 bytes
```

When `p2p_encrypt` is true, `TnpCamera` builds an application nonce and derived
password:

```text
connection prefix = 7 random characters, created by connect()
command suffix    = 8 random characters
nonce             = prefix + suffix              # 15 characters
canonical         = "user=xiaoyiuser&nonce=" + nonce
digest            = HMAC-SHA1(key=camera password, message=canonical)
derived password  = first 15 characters of Base64(digest)
authInfo          = ASCII(nonce + "," + derived password), zero-padded
```

This is distinct from the YI cloud request HMAC and from PPPP's license device
key. It authenticates each application command without sending the recovered
camera password verbatim in the TNP header.

## Evidence locations

- `.analysis/jadx/sources/com/tnp/model/TNPHead.java`
- `.analysis/jadx/sources/com/tnp/model/TNPFrameHead.java`
- `.analysis/jadx/sources/com/tnp/model/TNPIOCtrlHead.java`
- `.analysis/jadx/sources/com/tnp/model/TNP_Proto.java`
- `.analysis/jadx/sources/com/tnp/TnpCamera.java`
- `.analysis/jadx/sources/com/tutk/IOTC/AVFrame.java`
