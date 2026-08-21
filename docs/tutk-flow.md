# Cloud camera to TUTK H.264 flow

## Complete phase-1 chain

```mermaid
flowchart TD
    CRED[YI account + password] -->|GET /v4/users/login<br/>password = Base64 HMAC-SHA256| LOGIN[YI regional gateway]
    LOGIN -->|data.userid<br/>data.token<br/>data.token_secret| AUTH[In-memory user state]
    AUTH -->|GET /v4/devices/list<br/>HMAC-SHA1 key token&token_secret| LIST[Camera JSON array]
    LIST --> SELECT[Select camera<br/>type = 0<br/>model = 6 / yunyi.camera.y20]
    SELECT -->|uid| P2PID[P2PDevice.p2pid]
    SELECT -->|AES-decrypt password<br/>or PIN-gated password lookup| PWD[P2PDevice.pwd]
    SELECT -->|ipcParam.p2p_encrypt| ENC[P2PDevice.isEncrypted]
    P2PID --> TUTK[AntsCameraTutk / TutkCamera]
    PWD --> TUTK
    ENC --> TUTK

    TUTK --> INIT[IOTC_Initialize2(0)<br/>avInitialize(32)]
    INIT --> SID[IOTC_Get_SessionID]
    SID --> CONN[IOTC_Connect_ByUID_Parallel<br/>camera uid, sid]
    CONN --> AV[avClientStart2<br/>sid, nonce/username, auth password,<br/>timeout, service type, channel 0, resend]
    AV --> START[avSendIOCtrl<br/>START 511 or encrypted START2 8190<br/>payload = little-endian useCount]
    START --> RECV[avRecvFrameData2 loop<br/>300000-byte video buffer<br/>24-byte frame-info buffer]
    RECV --> DEC{Encrypted I-frame?}
    DEC -->|yes| AES[AES-ECB decrypt<br/>bytes 4..35 using cameraPassword + "0"]
    DEC -->|no| OUT[Compressed AVFrame]
    AES --> OUT
    OUT --> H264[codec_id 78: original compressed H.264 frame bytes]
```

This is the shortest proven chain to compressed frames. There is no RTSP, go2rtc, Frigate, firmware modification, or decoder in it.

## Object trace

| Stage | Field/value | Next consumer |
|---|---|---|
| `/v4/devices/list` | `uid` | `DeviceInfo.f7473c`, `d`, and `e` |
| `DeviceInfo` | `e == uid` | `P2PDevice.p2pid` |
| `/v4/devices/list` | decrypted `password`, or PIN lookup result | `DeviceInfo.i` -> `P2PDevice.pwd` |
| `ipcParam` | `p2p_encrypt` (default `true`) | `P2PDevice.isEncrypted` |
| `/v4/devices/list` | `type == 0` | `AntsCameraManage` selects `AntsCameraTutk` |
| feature config | model `6` -> `yunyi.camera.y20` | `P2PDevice.model` |
| `AntsCameraTutk` | `p2pid`, account, password, encryption flag, model, byte order | `new TutkCamera(...)` |
| `TutkCamera` | `mDevUID` set from `getUID()` | `IOTC_Connect_ByUID_Parallel(mDevUID, sid)` |
| `TutkCamera.AVChannel` | AV index from `avClientStart2` | Every `avSendIOCtrl` and `avRecvFrameData2` call |

`P2PDevice` normalizes the empty account passed by `DeviceInfo.c()` to the literal `admin`.

## SDK initialization

`AntsApplication.onCreate()` calls `TutkCamera.init()`. On the first reference:

```java
IOTCAPIs.IOTC_Initialize2(0);
AVAPIs.avInitialize(mDefaultMaxCameraLimit * 16);
```

`mDefaultMaxCameraLimit` is `2`, so the ordinary initialization requests `32` AV channels. Reference counting prevents repeated initialization. Final uninitialization calls `avDeInitialize()` and `IOTC_DeInitialize()`.

The Java wrapper static initializers load `libIOTCAPIs.so` and `libAVAPIs.so`. The ARMv7 `T`-suffixed variants are packaged but not selected by any `System.loadLibrary` call found in the APK.

## IOTC connection

`AntsCameraManage.getAntsCamera(P2PDevice)` selects `AntsCameraTutk` for `type == 0`. Its constructor creates:

```java
new TutkCamera(
    p2pDevice.p2pid,
    p2pDevice.account,
    p2pDevice.pwd,
    p2pDevice.isEncrypted,
    p2pDevice.model,
    isByteOrderBig()
)
```

For all TUTK devices `AntsCamera.isByteOrderBig()` returns `false`, so command integers are little-endian.

`connect()`/`openCamera()` starts both the IOTC connection worker and the AV-channel worker. The IOTC worker performs:

```text
reservedSid = IOTC_Get_SessionID()
sid = IOTC_Connect_ByUID_Parallel(cameraUid, reservedSid)
IOTC_Session_Check_Ex(sid, info)
```

`St_SInfoEx.Mode` is mapped as `0 -> P2P`, `1 -> Relay`, and `2 -> LAN`. The cloud `ipcParam.ip` is not passed to the connection function. No cloud-supplied master-server, relay-server, license key, or security key is passed either. The Kalay library resolves its own infrastructure from the UID and its compiled/configured internals.

## AV authentication (`avClientStart2`)

The app uses the deprecated Java signature that the bundled native library still exports:

```java
int avClientStart2(
    int sid,
    String user,
    String password,
    int timeout,
    int[] serviceTypeOut,
    int channel,
    int[] resendOut
)
```

The configured timeout defaults to 15 seconds in `P2PParams`; the call uses AV channel `0`.

### Unencrypted mode

When `p2p_encrypt == false`:

```text
user     = "admin"
password = plaintext camera password
```

### Encrypted mode

When `p2p_encrypt == true`:

```text
nonce = 15 characters, each independently selected from [A-Za-z0-9]
message = "user=xiaoyiuser&nonce=" + nonce
digest = Base64(HMAC-SHA1(key=UTF-8(cameraPassword), message=UTF-8(message)))
derivedPassword = first 15 characters of digest

avClientStart2(
    sid,
    user = nonce,
    password = derivedPassword,
    timeout,
    serviceTypeOut,
    channel = 0,
    resendOut
)
```

`AntsUtil.genNonce(15)` creates a new `java.util.Random` for each character. That is a faithful observation, not a recommendation for new code.

No device-list `deviceKey` or distinct Kalay auth key enters this call. The inputs are the cloud UID, the recovered camera password, and the encryption boolean.

## Starting live video

`AntsCamera.startPlay()` defaults to live mode. `AntsCameraTutk.doStartPlayVideo()`:

1. sets channel index `0`;
2. starts the `TutkCamera.ThreadRecvVideo` worker;
3. calls `sendStartPlayCommand()` -> `goLive()` -> `doGoLive()`;
4. increments the one-byte use counter;
5. sends one of the following through the IOCTRL queue.

| Encryption flag | IOCTRL | Decimal | Payload |
|---|---|---:|---|
| false | `IOTYPE_USER_IPCAM_START` | 511 | current use counter represented as a 4-byte little-endian integer |
| true | `IOTYPE_USER_IPCAM_START2` | 8190 | same 4-byte little-endian payload |

The IOCTRL sending thread ultimately calls:

```java
AVAPIs.avSendIOCtrl(avIndex, commandType, payload, payload.length)
```

There is a named `START_RESP` constant `512` for the legacy start. The live-start path does not wait for a response object before beginning the frame receive loop.

Stopping display sends `IOTYPE_USER_IPCAM_STOP` (`767`) with eight zero bytes, stops the receive workers, and also sends the appropriate record-play stop command (`794` or encrypted variant `12718`).

## Receiving compressed frames

The video worker clears the native video buffer, then repeatedly invokes:

```java
int size = AVAPIs.avRecvFrameData2(
    avIndex,
    videoBuffer,          // byte[300000]
    300000,
    outFrameSize,         // int[1]
    frameInfoExpected,    // int[1]
    frameInfo,            // byte[24]
    24,
    outFrameInfoSize,     // int[1]
    frameNumberOrCodec    // int[1], passed into AVFrame constructor as frame number
);
```

When the return value is positive and no larger than 300,000, the code copies exactly that many bytes into a new array and constructs `AVFrame` with the 24-byte native frame-info block. `AVFrame` defines video codec ID `78` as H.264 and codec ID `81` as H.265. The target feature asset says `h265Support: 0`; the relevant output is therefore the camera's compressed H.264 bytes.

The receiver tracks frame numbers. A gap in P-frames marks the stream lost and drops subsequent P-frames until a new I-frame arrives. The app does not decode video before calling `IRegisterCameraListener.receiveVideoFrameData(AVFrame)`.

Important native errors handled by the loop include frame-not-ready `-20012`, lost/incomplete frame conditions `-20014`/`-20013`, and session/channel closure conditions such as `-20015`, `-20016`, `-20010`, and `-20000`.

## Encrypted I-frame handling

For an encrypted session, only frames whose frame-info flags mark them as I-frames are transformed in the TUTK receive path:

```text
AES key string = plaintext camera password + "0"
cipher         = AES/ECB/NoPadding
key bytes      = ASCII(AES key string)

if frame length >= 36:
    decrypt frame bytes [4, 20) as one 16-byte block
    decrypt frame bytes [20, 36) as one 16-byte block
    leave bytes [0, 4) and [36, end) unchanged
```

`AESIPC.decrypt` catches cipher failures and returns a copy of the original block, so an invalid AES key length results in an unchanged frame after a logged exception.

The key's origin is therefore exact:

```text
/v4/devices/list data[].password
  -> hex decode + AES-ECB-PKCS7 decrypt with uid[0:16]
  -> plaintext camera password
  -> append ASCII "0"
  -> AES-ECB-NoPadding key for two I-frame blocks
```

For PIN-protected devices, the plaintext password first comes from `/v5/devices/password` using the same cloud-password decryption procedure.

`decryptAudioFrame` and `encryptAudioFrame` exist, but their active uses found in this APK are in `TnpCamera`, not the target TUTK receive path. The TUTK audio worker does not call `decryptAudioFrame`.

## What is and is not ready for a bridge

Statically proven inputs for a type-0 Y20 session are:

- regional account login contract;
- `userid`, `token`, and `token_secret` for device discovery;
- camera `uid` used directly as the TUTK UID;
- plaintext camera password recovery, including the PIN-gated path;
- `p2p_encrypt` mode;
- `avClientStart2` nonce/password derivation;
- live-start command and payload byte order;
- compressed-frame receive call and I-frame decryption.

Still **UNKNOWN/unverified** before a robust local bridge:

- whether current production accounts still accept the 2022 API and embedded login transform;
- current error/rate-limit/MFA behavior;
- whether every Y20 account returns `type == 0` and the same password format;
- native Kalay server-selection internals and any service-side UID migration;
- exact Annex B vs length-prefixed H.264 byte layout for real Y20 frames (the app passes bytes through; a capture is needed to verify framing);
- SPS/PPS repetition and reconnect behavior on real hardware.

Those unknowns require controlled dynamic observation, not guessed implementation. RTSP/go2rtc/Frigate remains intentionally out of scope.
