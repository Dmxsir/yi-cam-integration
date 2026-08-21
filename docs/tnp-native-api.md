# TNP native PPPP API

## Packaged binaries

The APK packages the same Java-facing PPPP API for two Android ARM ABIs:

| APK path | Format | Size | SHA-256 |
|---|---|---:|---|
| `lib/arm64-v8a/libPPPP_API.so` | ELF64, AArch64 | 243,576 | `83FEED8079AA6E6E955DEBA13640FB8658AAB3DB8CFCD0B8BF74201F087D729C` |
| `lib/armeabi-v7a/libPPPP_API.so` | ELF32, ARM EABI | 202,320 | `6CF7BD00233E16103897D2CD60EB92B7B30E9CFFFE22B30C122A29BDC396D050` |

Both depend on Android `liblog.so`, `libstdc++.so`, `libc.so`, `libm.so`, and
`libdl.so`. They are Android ARM binaries, not drop-in x86-64 Linux shared
objects. Static ELF inspection found 441 exported symbols in ARM64 and 538 in
ARMv7; the PPPP and named JNI subsets relevant here are present in both.

## Loading and initialization

`AntsApplication.k()` calls `System.loadLibrary("PPPP_API")`. The Java binding
is `com.p2p.pppp_api.PPPP_APIs`. Camera database-manager initialization calls:

```java
PPPP_APIs.PPPP_Initialize(new byte[] { 0 }, 12);
```

The second argument is the configured maximum session count. Teardown calls
`PPPP_DeInitialize()`.

## Java/JNI surface

The named JNI exports in both binaries use the prefix
`Java_com_p2p_pppp_1api_PPPP_1APIs_` and cover:

```text
PPPP_Check                 PPPP_CheckDevOnline
PPPP_Check_Buffer          PPPP_Close
PPPP_Config_Debug          PPPP_Connect
PPPP_ConnectByServer       PPPP_ConnectOnlyLanSearch
PPPP_Connect_Break         PPPP_DeInitialize
PPPP_ForceClose            PPPP_GetAPIVersion
PPPP_Initialize            PPPP_IsConnecting
PPPP_Listen                PPPP_Listen_Break
PPPP_LoginStatus_Check     PPPP_NetworkDetect
PPPP_Probe                 PPPP_Read
PPPP_SendLogin             PPPP_Set_Log_Filename
PPPP_Share_Bandwidth       PPPP_WakeUp_And_Connect
PPPP_Write
```

The Java declarations and their application-level signatures are:

| Method | Java signature |
|---|---|
| `PPPP_Initialize` | `(byte[] init, int maxSessions) -> int` |
| `PPPP_DeInitialize` | `() -> int` |
| `PPPP_Connect` | `(String did, byte flag, int udpPort, String server, String deviceKey) -> int` |
| `PPPP_ConnectByServer` | same five parameters -> `int` |
| `PPPP_WakeUp_And_Connect` | same five parameters -> `int` |
| `PPPP_Connect_Break` | `(String did) -> int` |
| `PPPP_Check` | `(int handle, st_PPPP_Session outSession) -> int` |
| `PPPP_Check_Buffer` | `(int handle, byte channel, int[] writeSize, int[] readSize) -> int` |
| `PPPP_Read` | `(int handle, byte channel, byte[] buffer, int[] inOutSize, int timeout) -> int` |
| `PPPP_Write` | `(int handle, byte channel, byte[] buffer, int size) -> int` |
| `PPPP_Close` | `(int handle) -> int` |
| `PPPP_ForceClose` | `(int handle) -> int` |
| `PPPP_CheckDevOnline` | `(String did, String server, int timeout, int[] result) -> int` |
| `PPPP_Probe` | `(String did, int timeout, byte[] output, int outputSize) -> int` |
| `PPPP_NetworkDetect` | `(st_PPPP_NetInfo output, int udpPort) -> int` |
| `PPPP_Listen` | `(String did, int timeout, int udpPort, byte flag, String server, String key) -> int` |
| `PPPP_Listen_Break` | `() -> int` |
| `PPPP_LoginStatus_Check` | `(byte[] output) -> int` |
| `PPPP_SendLogin` | `() -> int` |
| `PPPP_IsConnecting` | `() -> int` |
| `PPPP_GetAPIVersion` | `() -> int` |
| `PPPP_Config_Debug` | `(byte enabled, int level) -> int` |
| `PPPP_Set_Log_Filename` | `(String path) -> int` |
| `PPPP_Share_Bandwidth` | `(byte enabled) -> int` |

Java also declares the misspelled `PPPP_ConnectForDoolBell` with the five
connect parameters. A corresponding named JNI export was not found. It could be
dynamically registered or unused; its availability is **UNKNOWN**. Conversely,
symbol lists can contain native functionality that the inspected Java binding
does not declare.

## Direct native exports

In addition to JNI trampolines, both binaries expose a direct C-style PPPP
surface. Relevant names include:

```text
PPPP_Initialize             PPPP_DeInitialize
PPPP_Connect                PPPP_ConnectByServer
PPPP_ConnectOnlyLanSearch   PPPP_Connect_LanOnly
PPPP_Connect_Break          PPPP_Connect_Break_All
PPPP_Listen                 PPPP_Listen_Proxy
PPPP_Listen_Break           PPPP_Check
PPPP_Check_Buffer           PPPP_Read
PPPP_Write                  PPPP_Close
PPPP_ForceClose             PPPP_IsConnecting
PPPP_NetworkDetect          PPPP_Parse_Address
PPPP_Probe                  PPPP_CheckDevOnline
PPPP_Check_DevOnline        PPPP_SendLogin
PPPP_Send_Login             PPPP_WakeUp
PPPP_WakeUp_And_Connect     PPPP_Share_Bandwidth
PPPP_GetAPIVersion          PPPP_Get_APIVersion
PPPP_GetPeerBandwidthInfo   PPPP_Get_PeerBandwidthInfo
PPPP_Get_Statistics         PPPP_Update_Network
```

Export presence proves symbol availability, not an independently documented C
ABI, redistribution right, or ordinary Linux compatibility.

## Exact official connection calls

`TnpCamera.RunnableConnect` computes either flag `0x4B` (normal/direct policy)
or `0x5F` (forced relay policy) and passes:

```text
argument 1: p2pid                 <- /v4/tnp/device_info data.DID
argument 2: connection flag       <- 0x4B or 0x5F
argument 3: UDP port              <- 0
argument 4: serverString          <- data.InitString
argument 5: licenseDeviceKey      <- first component of data.License
```

If `ipcParam.wakeup` is true it uses `PPPP_WakeUp_And_Connect`; otherwise it
uses `PPPP_Connect`. The return value is treated as a session handle when it is
non-negative. It then calls `PPPP_Check` and starts its channel workers.

The official TNP camera does not use `PPPP_SendLogin` in this path. Command
authentication is implemented in `TNPIOCtrlHead`, described in
[tnp-protocol.md](tnp-protocol.md).

## Scope warning

This file records the Phase 2B static result. Phase 2C subsequently invoked the
untouched ARM64 library in an isolated Android emulator, with secrets delivered
over an in-memory localhost socket rather than command-line arguments. The
controlled result and its limitations are documented in
[phase-2c-report.md](phase-2c-report.md).

## Evidence locations

- APK binaries: `.analysis/apk/lib/*/libPPPP_API.so`
- Java declarations:
  `.analysis/jadx/sources/com/p2p/pppp_api/PPPP_APIs.java`
- connection calls: `.analysis/jadx/sources/com/tnp/TnpCamera.java`
- library loader:
  `.analysis/jadx/sources/com/ants360/yicamera/AntsApplication.java`
