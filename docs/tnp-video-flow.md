# TNP live-video command and receive flow

## Starting live video

The active call chain is:

```text
AntsCamera.startPlay()
  -> AntsCameraTnp.doStartPlayVideo()
  -> sendStartPlayCommand()
  -> goLive()
  -> doGoLive()
  -> TnpCamera.sendIOCtrl()
```

`doGoLive()` increments the camera's `useCount` and queues command:

```text
IOTYPE_USER_IPCAM_TNP_START_REALTIME = 9029 = 0x2345
```

`SMsgAVIoctrlTnpPlay.parseContent(useCount, resolutionType, 1)` creates exactly
four payload bytes:

| Offset | Size | Value |
|---:|---:|---|
| 0 | 1 | current `useCount` |
| 1 | 1 | selected `resolutionType` (default 0) |
| 2 | 1 | payload version 1 |
| 3 | 1 | reserved zero |

The send thread wraps this payload in a 40-byte `TNPIOCtrlHead`, then an 8-byte
`TNPHead`, and calls `PPPP_Write(session, channel=0, buffer, size)`.

No command-specific response constant or required response payload for 9029 was
identified. The command channel can carry a correlated response, but treating a
particular response as mandatory is **UNKNOWN** until a controlled capture.

Stopping display uses `IOTYPE_USER_IPCAM_STOP = 767 (0x02FF)` with eight zero
bytes. Playback uses different commands and channels and is outside the live
bridge scope.

## Receiving compressed video

Realtime video has separate workers:

| PPPP channel | Worker | Buffer ceiling in APK |
|---:|---|---:|
| 2 | realtime I-frame receiver | 1 MiB |
| 3 | realtime P-frame receiver | 307,200 bytes |

For every unit the worker:

1. reads and removes the 8-byte `TNPHead`;
2. reads `TNPHead.dataSize` bytes;
3. parses the first 24 bytes as `TNPFrameHead` through `AVFrame`;
4. copies the remaining bytes as the original compressed payload;
5. conditionally decrypts encrypted I-frame blocks;
6. applies stream-generation and frame-order checks;
7. dispatches the compressed `AVFrame` to the listener/decoder.

The compressed payload is therefore at byte 24 of the video body and byte 32
from the start of the outer TNP unit.

### Ordering and stream generation

- An I-frame establishes the current decode point and is accepted immediately.
- A P-frame is emitted immediately only when its sequence follows the last
  emitted frame.
- Out-of-order future P-frames are queued, then drained as the missing sequence
  arrives. The queue is capped at 100 and drops its oldest entry when full.
- Frames at or behind the last emitted sequence are discarded.
- `useCount` rejects frames from a previous start-play generation, with a narrow
  initial I-frame accommodation in the APK.

Although channels separate expected I and P frames, the header's flags byte is
also parsed; `AVFrame.isIFrame()` checks bit 0.

## Codec and elementary-stream format

The active parser recognizes H.264 codec ID `78` and H.265 codec ID `81`.
Feature configuration for `y21ga` and `y291ga` has `h265Support=0`, which is
strong static evidence that those models request/produce H.264 in this APK.
The actual codec ID from this production camera has not been captured and
remains **UNKNOWN**.

No code in `TnpCamera` extracts, prepends, or rewrites SPS/PPS NAL units. Apart
from the encrypted-I-frame operation below, it passes the compressed payload
unchanged to the downstream listener/decoder.

The first four compressed-payload bytes are deliberately preserved by
`decryptIframe()`. They could be an Annex-B start code or a length prefix. The
APK path inspected here does not distinguish them, so all of the following are
**UNKNOWN** until a packet-safe Phase 2C capture:

- Annex B versus length-prefixed NAL units;
- whether SPS/PPS appear in-band on each keyframe, only initially, or separately;
- the production camera's exact codec ID and resolution selection values.

## TNP media encryption

For a device with `ipcParam.p2p_encrypt=true`, `TnpCamera` creates:

```text
AES key = UTF-8(recovered camera password + "0")
```

For an I-frame only, `decryptIframe()`:

1. preserves compressed-payload bytes 0..3;
2. decrypts bytes 4..19 as one AES-ECB/NoPadding block;
3. decrypts bytes 20..35 as a second AES-ECB/NoPadding block;
4. preserves every remaining byte.

P-frames are not AES-decrypted. This operation is separate from TNP
IO-control's nonce/HMAC authentication. The key comes from the recovered camera
password—not from the cloud token, token secret, `InitString`, or license.

For TNP header version 2 or newer, received audio decrypts every complete
16-byte block with the same key, and outgoing audio encrypts complete blocks.
Trailing partial bytes are not included in an AES block.

## Phase 2B stop matrix — selected production `y21ga`

No P2P call was made. “Available” means present and non-empty in memory during
the authorized cloud-only validation; secret values are not reported.

| Required fact/input | Status | Evidence / boundary |
|---|---|---|
| Cloud UID | AVAILABLE | `<REDACTED_TNP_DID>` |
| Raw / normalized model | CONFIRMED | `51` / `y21ga` from APK feature assets |
| P2P implementation | CONFIRMED | type 2 / TNP |
| Recovered camera password | AVAILABLE | recovery succeeded; value never printed or persisted |
| Usable P2P password | AVAILABLE | in-memory descriptor check succeeded |
| `p2p_encrypt` | CONFIRMED | true |
| PPPP DID | AVAILABLE | `/v4/tnp/device_info.data.DID`; value withheld |
| PPPP server/init string | AVAILABLE | `data.InitString`; value withheld |
| Full license | AVAILABLE | two components; value withheld |
| Native license device key | AVAILABLE | first license component; value withheld |
| Meaning of license component 2 | UNKNOWN | no proven consumer/semantic label |
| Native connect function and argument order | CONFIRMED STATICALLY | `PPPP_Connect` / wakeup variant, five arguments |
| Command authentication | CONFIRMED STATICALLY | nonce + first 15 Base64 HMAC-SHA1 characters |
| TNP header layouts / endianness | CONFIRMED STATICALLY | 8/24/40-byte big-endian structures |
| Live-start command and payload | CONFIRMED STATICALLY | 9029, four bytes |
| Realtime receive channels | CONFIRMED STATICALLY | I=2, P=3 |
| I-frame decryption | CONFIRMED STATICALLY | AES-ECB two blocks after four-byte prefix |
| Actual negotiated header version | UNKNOWN | initial 2, runtime detection not exercised |
| Actual live codec and dimensions | UNKNOWN | model assets indicate no H.265 support; no capture |
| Annex B / SPS/PPS behavior | UNKNOWN | no live compressed payload inspected |
| Native PPPP connection | NOT PERFORMED | explicitly outside Phase 2B |

The selected target therefore has all cloud-derived inputs needed for a
controlled Phase 2C PPPP connection experiment: DID, initialization string,
license device key, camera password, and `p2p_encrypt`. Protocol construction is
sufficiently documented to design that experiment, but not yet to claim a
container-ready stream.

## Evidence locations

- type-2 adapter:
  `.analysis/jadx/sources/com/xiaoyi/camera/sdk/AntsCameraTnp.java`
- TNP session/workers: `.analysis/jadx/sources/com/tnp/TnpCamera.java`
- TNP play payload and IO-control models under
  `.analysis/jadx/sources/com/tutk/IOTC/`
- compressed frame parser:
  `.analysis/jadx/sources/com/tutk/IOTC/AVFrame.java`
