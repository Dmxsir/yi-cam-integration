# Current YI client comparison (Phase 2C.1)

## Evidence boundary

Evidence labels used here:

- `APK_PROVEN`: YI Home 5.6.5 (`versionCode 319`, August 2022).
- `CURRENT_CLIENT_PROVEN`: complete installed YI Home 6.9.7 APK set supplied read-only.
- `LIVE_CAMERA_PROVEN`: the earlier controlled y291ga custom-oracle session.
- `PCAP_RUNTIME_PROVEN`: the later Phase 2C.2 official POOL captures.
- `UNKNOWN`: not established by static artifacts or an approved live trace.

No official Live View, cloud request, or custom PPPP connection was made during
the Phase 2C.1 static pass. Phase 2C.2 later supplied official network traces;
its runtime addendum appears at the end. Private app storage was not accessed.

## Installed package set

The complete installed package set is available under the ignored
`current-client-full/` directory. It was not modified.

| APK | Bytes | SHA-256 |
|---|---:|---|
| `base.apk` | 127,997,421 | `32F0A018A0A5BD2166EC090242252E53F50516E0868CEB8ACB249639ECDD88D4` |
| `split_config.arm64_v8a.apk` | 63,271,310 | `D6A5D1774F6B6D1028D1E3E45B5B275080B05111CB60ADBE858E6004EC3379DF` |
| `split_config.en.apk` | 406,015 | `137DEC52E7545AD647D6173761D614674277C29EBB6ED1A38397BC7951CB4AC4` |
| `split_config.iw.apk` | 139,673 | `650FE7CB955EFF4246420260E138A738054A685FF19CFB62EF111CAA7BF6BF13` |
| `split_config.xxxhdpi.apk` | 1,788,673 | `7B4FA3892A8201D7D1F00CABCBBB25D7000949595A60491443054F89FE9A617B` |

Installed-client metadata:

| Property | Value | Evidence |
|---|---|---|
| Package | `com.ants360.yicamera.international` | `CURRENT_CLIENT_PROVEN` |
| Version | `6.9.7_20260820043046` | `CURRENT_CLIENT_PROVEN` |
| Version code | `453` | `CURRENT_CLIENT_PROVEN` |
| Device | Realme RMX3709 / RMX3709EX | supplied installed-package context |
| Native ABI | ARM64 / AArch64 | APK split and ELF headers |
| Native libraries in ABI split | 54 | archive inventory |

`current-client-full/`, `current-client-decompiled/`, and
`current-native-analysis/` are covered by `.gitignore`.

## Native PPPP result

The current proprietary transport is **CHANGED**, not removed or replaced.
The public C and JNI surface remains compatible, but the binary, API version,
and internal symbol set differ.

| Property | 2022 client | Current 6.9.7 client |
|---|---|---|
| File | `libPPPP_API.so` | `libPPPP_API.so` |
| Architecture | ELF64 AArch64 | ELF64 AArch64 |
| Size | 243,576 bytes | 243,264 bytes |
| SHA-256 | `83FEED8079AA6E6E955DEBA13640FB8658AAB3DB8CFCD0B8BF74201F087D729C` | `8C53F2ECC7CE6C362960AF29A5D8DE8396347A120DC10E88B24928437C4286EB` |
| Dynamic exports | 448 with the current inventory rules | 462 |
| API version | `0xA2030401` | `0xA2050401` |
| Classification | old reference | **CHANGED** |

The current API version was recovered without a camera connection. The
AArch64 `PPPP_GetAPIVersion` export branches to `PPPP_Get_APIVersion`; its
constant-building instructions return `0xA2050401`. An offline regression test
checks this exact decode.

Both libraries export the required public surface:

```text
PPPP_GetAPIVersion
PPPP_Initialize
PPPP_DeInitialize
PPPP_Connect
PPPP_ConnectByServer
PPPP_Check
PPPP_Read
PPPP_Write
PPPP_SendLogin
PPPP_Close
PPPP_ForceClose
PPPP_WakeUp
PPPP_WakeUp_And_Connect
```

All 26 exported Java/JNI wrappers found in the old binary also exist in the
current binary. Current internal additions include version-2 block-write and
keepalive helpers, P2P server/domain handling, and new wake/connect variants.
These additions prove native drift, but static symbol names alone do not prove
which one explains a post-write remote close.

## PPPP initialization and connection policy

The 2022 client initializes with one zero byte and a 12-session limit:

```text
PPPP_Initialize(<one zero byte>, 12)
```

The current client has a remotely controlled `newP2PStrategy`:

- disabled: the same one-zero-byte initializer;
- enabled: UTF-8 bytes from the saved current TNP server/init string, with the
  same 12-session limit;
- enabled but missing string: falls back to one zero byte.

The string is obtained from the current TNP information flow and stored by the
official app under its TNP server-string preference. No value or private
preference was read. The production setting for this account is `UNKNOWN`.
The Java boundary is
`com.p2p.pppp_api.PPPP_APIs.PPPP_Initialize(byte[], int)` and the current
AArch64 library exports both its JNI wrapper and the direct
`PPPP_Initialize` entry point. Thus the byte array above is the exact input
passed across JNI; the native implementation's internal decoding is opaque.

The connection flag changed:

```text
2022: (tryCount << 1) | 0x41
2026: (connectMode << 7) | (tryCount << 1) | 0x41
```

| Direct path | Try value | Flag |
|---|---:|---:|
| 2022 / old oracle | 5 | `0x4B` |
| current legacy strategy | 4 | `0x49` |
| current new-strategy first direct attempt | 3 | `0x47` |

The old oracle established a direct session with `0x4B`, so this is a proven
parity gap but not a proven cause of the later application-layer close.

## TNP framing and authentication

No current-client change was found in the outgoing TNP or IOCTRL layout.
Type-2 fields remain big-endian.

### Outer header

| Offset | Size | Current meaning | Comparison |
|---:|---:|---|---|
| 0 | 1 | application version | `MATCH` |
| 1 | 1 | stream/IO type | `MATCH` |
| 2 | 1 | emitted zero; parsed as `abilityRet` on input | output `MATCH`, input semantics extended |
| 3 | 1 | reserved zero | `MATCH` |
| 4 | 4 | body length, big-endian | `MATCH` |
| total | 8 | `TNPHead.LEN_HEAD` | `MATCH` |

### IOCTRL header

| Offset | Size | Meaning | Comparison |
|---:|---:|---|---|
| 0 | 2 | command/type, big-endian | `MATCH` |
| 2 | 2 | command number, big-endian | `MATCH` |
| 4 | 2 | extended-header size, big-endian | `MATCH` |
| 6 | 2 | payload size, big-endian | `MATCH` |
| 8 | 32 | outgoing `authInfo` | `MATCH` |
| total | 40 | `TNPIOCtrlHead.LEN_HEAD` | `MATCH` |

Authentication also matches the 2022 implementation exactly:

| Property | Current value | Comparison |
|---|---|---|
| Session nonce prefix | 7 alphanumeric characters | `MATCH` |
| Per-command suffix | 8 alphanumeric characters | `MATCH` |
| Total nonce | 15 characters | `MATCH` |
| Generator | Java `Random`, per character | `MATCH` |
| HMAC | HMAC-SHA1 | `MATCH` |
| Key source | recovered camera password | `MATCH` |
| Input shape | `user=xiaoyiuser&nonce=<nonce>` | `MATCH` |
| Base64 | standard alphabet and padding | `MATCH` |
| Digest component used | first 15 of 28 characters | `MATCH` |
| Serialized auth length | 31 bytes | `MATCH` |
| Field capacity / termination | 32 bytes / final zero byte | `MATCH` |

No auth contents were emitted. `PPPP_SendLogin` remains unused on this TNP
path; authentication is embedded in ordinary channel-0 IOCTRL messages.

Both clients initially send application version 2 when
`P2PDevice.tnpHeaderVersion` is zero. A different version returned by the peer
is then adopted and the initial request resent. Phase 2C.2 subsequently proved
that both successful official POOL sessions stayed on application version 2.

## Current player routing

The current home-screen route is deterministic from device ability state:

```text
isBallCamera() || isMixBallCamera()
  -> com.xiaoyi.yiplayer.ui.PlayerActivity
  -> BallCameraPlayerFragment

otherwise
  -> com.ants360.yicamera.activity.camera.PlayerActivity
  -> CameraPlayerV2Fragment / CameraPlayerFragment
```

`isBallCamera()` uses the remote `DUAL_CAM` ability. `isMixBallCamera()` uses
`DUAL_CAM_MIX` or the version-gated `DUAL_CAM_NEW` ability. These are populated
from `/v8/device/ability/list`, not solely from the bundled y291ga feature
asset. The current POOL ability booleans were not fetched or read, so its
actual route is `UNKNOWN` and is not guessed.

The full static decision tree for a normal device-card selection is:

```text
offline/PIN/permission/access gates
  -> may block or prompt, but do not choose the player implementation

online, permitted selection
  -> DUAL_CAM supported
       -> BallCameraPlayerFragment
  -> else DUAL_CAM_MIX supported
       -> BallCameraPlayerFragment
  -> else DUAL_CAM_NEW supported and firmware/version gate passes
       -> BallCameraPlayerFragment
  -> else
       -> CameraPlayerV2Fragment / CameraPlayerFragment

selected player creates P2PDevice
  -> type 2 selects AntsCameraTnp/TnpCamera
  -> appParam, ipcParam and connection strategy populate connection/features
     but do not participate in the home-screen player-class branch
```

Raw model 83/y291ga, device type 2, appParam, ipcParam, and the `0x47`/`0x49`
connection-strategy branch are therefore insufficient to resolve the UI route.
The one missing route input is POOL's current remote ability state.

Static startup sequences are:

| Current path | Java queue order | First packet |
|---|---|---:|
| legacy/main `CameraPlayerFragment` | 9029, then 816 about 100 ms later | 52 bytes |
| `BallCameraPlayerFragment` P2P path | 4881, then 816, then 9029 | 56 bytes |
| `SinglePlayerFragment2` | 4881, then 9029; later requests are state-dependent | 56 bytes |

For the Ball path, `onResume()` calls resolution setup, device-info request,
and player resume in that order. These enqueue 4881 (8-byte payload), 816
(4-byte payload), and 9029 (4-byte payload). There is no fixed delay between
those three Java calls. This is static queue-order evidence, not a live native
write trace.

The old 56-byte oracle packet remains structurally valid for a 4881 request;
the primary unresolved question is whether POOL currently takes the path that
sends it first.

For a fresh legacy/main type-2 camera, the first 9029 packet is structurally:

| Field | Value/source |
|---|---|
| outer application version | 2 while `tnpHeaderVersion == 0` detection is pending |
| outer stream type | IOCTRL / 3 |
| outer body length | 44 bytes |
| IOCTRL command | 9029 / `0x2345` |
| IOCTRL command number | first queue increment, normally 1 on a fresh object |
| IOCTRL payload length | 4 bytes |
| payload byte 0 | use count incremented from 0 to 1 |
| payload byte 1 | runtime resolution; preference default maps to 2, but saved/relay policy may change it |
| payload byte 2 | command version literal 1 |
| payload byte 3 | reserved literal 0 |
| total | 8 + 40 + 4 = 52 bytes |

On the Ball path, 4881 and 816 are queued first. The later 9029 therefore has
a later command number and use count. Phase 2C.2 resolved the production
runtime values separately below; the static fragment candidates do not by
themselves describe the full native queue.

## Dynamic instrumentation feasibility

The complete current manifest has neither `android:debuggable="true"` nor a
`profileable` declaration. The native split contains no Frida Gadget or
equivalent embedded instrumentation library. On an ordinary non-root Android
device, `adb shell` cannot attach Frida, LLDB, JDWP, or JVMTI to this release
app's separate UID.

The app's own release logging is unsuitable: some existing Java log calls
include sensitive P2P material. Capturing broad `adb logcat` output would not
meet this phase's secret-safety requirements.

`tools/yi_tnp_trace.js` is therefore prepared but not run. It hooks
`PPPP_Initialize`, connect/check, `PPPP_Write`, and `PPPP_Read`, parses only the
first five channel-0 writes and reads in memory, and emits structural fields
only. It never reads packet buffers into a byte array, emits hex, or prints
secret strings. The least-invasive acceptable future attachment route is an
already-authorized rooted/test device with Frida server, or an official
debuggable/profileable equivalent build. Rooting, patching, re-signing,
reinstalling, or adding Gadget to the user's official app is outside scope.

```text
instrumentation parser: READY
attachment route on current stock device: BLOCKED
network PCAP route: COMPLETED
READY_FOR_OFFICIAL_POOL_TRACE: COMPLETE
```

## Phase 2C.2 production runtime addendum

The non-root PCAP route resolved the static uncertainties without modifying
the official client. Current 6.9.7 opened POOL successfully over direct UDP to
`10.0.0.150` and used TNP version 2 throughout.

| Property | Current 6.9.7 | Older official capture | Failed oracle |
|---|---|---|---|
| Exact client version | `6.9.7_20260820043046` / 453 | `UNKNOWN` | local oracle using 2022 native library |
| PPPP API | `0xA2050401` statically proven | `UNKNOWN` | `0xA2030401` live proven |
| TNP application version | 2 | 2 | 2 |
| first command | 9031 | 4881 | 4881 |
| first TNP size | 72 | 56 | 56 |
| first DRW application group | 9031 alone | 4881 + 9029 + 768 | 4881 only before blocking read |
| first camera command response | 9032 at 326.915 ms | 4882 at 34.209 ms | none; `-3012` after about 11 s |
| live media | success | success | none |

This runtime evidence confirms no application-version drift and no outer or
IOCTRL/authInfo layout drift. The current native library is still changed, and
the official captures additionally prove a transport behavior difference:
current phone alive messages carry four bytes while the older phone messages
carry zero bytes. The four-byte current value is not identical to
`PPPP_GetAPIVersion`, so its exact semantics remain `UNKNOWN`.

The old static route table remains useful for caller candidates, but Capture A
is authoritative for actual POOL behavior: an event-list request (9031) wins
the channel-0 queue, then a seven-command burst begins with 9029 3.028 ms
later. See `docs/tnp-network-golden-trace.md` for the complete timeline.
