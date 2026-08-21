# Current ARM64 native parity inventory

## Scope

The complete `split_config.arm64_v8a.apk` from installed YI Home
`6.9.7_20260820043046` was inspected read-only. Its 54 shared libraries were
extracted only to the ignored `current-native-analysis/` working directory.
The full machine-readable inventory, including every dynamic export and
dependency, is:

```text
current-native-analysis/current-arm64-native-inventory.json
```

`tools/elf_inventory.py` generated the inventory without external packages.

## Relevant current libraries

| Library | Bytes | Exports | SHA-256 | Key dependencies |
|---|---:|---:|---|---|
| `libPPPP_API.so` | 243,264 | 462 | `8C53F2ECC7CE6C362960AF29A5D8DE8396347A120DC10E88B24928437C4286EB` | `liblog`, `libstdc++`, `libm`, `libc`, `libdl` |
| `libIOTCAPIs.so` | 334,040 | 554 | `AFFC4BBD9995F3466CBC5519200045D329B869693EC5D7FAE9C7DE69C9A51EB1` | `liblog`, `libc`, `libm`, `libstdc++`, `libdl` |
| `libAVAPIs.so` | 210,616 | 366 | `C70A304726B8197C0198A3C16BC02480E6D5FDB09E92912D7210660C0EE4DADD` | `libIOTCAPIs`, `libsCHL`, libc/math/runtime |
| `libcrypto.so` | 4,679,288 | 5,603 | `8852C7BD5C1113D0C6F8AEC750B36B8D0A75F7DDAC7DD40E5BD4ABE5DF99A4A3` | `libdl`, `libc` |
| `libssl.so` | 884,008 | 583 | `3B5769038140BE55ABD28E52AA5C03BCAEA81392F90AA19000B362DDD3573B78` | `libcrypto`, `libdl`, `libc` |
| `libyimedia.so` | 109,224 | 9 | `1FAFB9AD7F621AB7FA76A43C0F88853DC82CE954AAA3B8FCCC750473310E64F4` | `liblog`, `libijkffmpeg`, libc/math/runtime |
| `libaudioproc.so` | 5,886,616 | 2,021 | `F08B62DCF6938DAE60925B6A3523AF260474B69D6D8ED76BF533193EC7450AA0` | WebRTC audio preprocessing, libc/math/runtime |
| `libwebrtc_audio_preprocessing.so` | 839,088 | 1,799 | `47A0F5BF8F1EE5446E7BFAD05F7D4FC14DA27A7D569D1D61895B0F2C82C7363C` | C++ shared runtime, log, libc/math |
| `libVoAACEncoder.so` | 129,168 | 161 | `1492705D810F26D860662A6BDD6035EB337C16CD1F5A23D0495696479A6C4EC0` | audio codec runtime |
| `libG726Android.so` | 60,960 | 14 | `D4D225412ABC2E78ED5B416C50E8CEDFF65335BD67EEB5E37D5F961A06A72DAB` | audio codec runtime |
| `libh265decoder.so` | 135,336 | 20 | `70660A61D8C87FDCDC0602C13302F5782FE581A5F88296509240FDAD61D8B17A` | decoder runtime |

All listed binaries are ELF64 AArch64. Library names and hashes are not secret
credential material.

## `libPPPP_API.so` comparison

| Property | Old 2022 | Current 2026 |
|---|---|---|
| SHA-256 | `83FEED8079AA6E6E955DEBA13640FB8658AAB3DB8CFCD0B8BF74201F087D729C` | `8C53F2ECC7CE6C362960AF29A5D8DE8396347A120DC10E88B24928437C4286EB` |
| Size | 243,576 | 243,264 |
| API version | `0xA2030401` | `0xA2050401` |
| Export count | 448 | 462 |
| Core public API | present | present |
| Classification | reference | **CHANGED** |

The current binary retains the public core API and all previously identified
JNI wrappers. Internal current-only exports include version-2 block write,
version-2 alive/ack, domain-based P2P server resolution, P2P server timing, and
new const-correct encode/decode/connect/wakeup variants. Several old mangled
symbols disappear because their signatures were replaced, not because the
public feature was removed.

The complete current-only export-name set from the two inventories is:

```text
_Z13PPPP_DoWakeupPKcS0_S0_
_Z14PPPP_DoConnectPKcctS0_S0_c
_Z18PPPP_GetHostByNameP11sockaddr_in
_Z27PPPP_UpdateP2PServerAckTimeP11sockaddr_in
_Z27PPPP_UsingDomanForP2PServerP11sockaddr_in
_ZN3tnp12getCurSecondEmj
_ZN3tnp15PPPP_DebugTraceEjPKcz
_ZN3tnp16PPPP_DRWReq_SendEicP11sockaddr_inht
_ZN3tnp16pthread_set_nameEPKc
_ZN3tnp17PPPP_DecodeStringEPKcPci
_ZN3tnp17PPPP_EncodeStringEPKcPci
_ZN3tnp17gP2PServerAckTimeE
_ZN3tnp17gUsingDomainFor4GE
_ZN3tnp18PPPP__Write_Block2EihPciy
_ZN3tnp20PPPP__Write_Block_v2EihPciy
_ZN3tnp23PPPP_DRWReq_Read_HeaderEPNS_17st_PPPP_DRWHeaderEPhPt
_ZN3tnp23sll_element_Allocate_V2Ejjy
_ZN3tnp24PPPP_Proto_Send_Alive_v2EicP11sockaddr_in
_ZN3tnp25PPPP__Decode_ServerStringEPKcP11sockaddr_ini
_ZN3tnp27PPPP_Proto_Send_AliveAck_v2EicP11sockaddr_inj
_ZN3tnp27__inline_PPPP_DebugTrace_V2EjPKcjS1_z
_ZN3tnp30PPPP__Resolve_SessionP2PServerEiPKc
```

The old-only export-name set is:

```text
_Z13PPPP_DoWakeupPKcPcS1_
_Z14PPPP_DoConnectPKcctPcS1_c
_ZN3tnp12getCurSecondElj
_ZN3tnp15PPPP_DebugTraceEjPcz
_ZN3tnp17PPPP_DecodeStringEPcS0_i
_ZN3tnp17PPPP_EncodeStringEPcS0_i
_ZN3tnp25PPPP__Decode_ServerStringEPcP11sockaddr_ini
_ZN3tnp30PPPP__Resolve_SessionP2PServerEiPc
```

These old-only entries are older parameter variants of `PPPP_DoConnect`,
`PPPP_DoWakeup`, encode/decode helpers, server-string decode, and P2P-server
resolution. Their current const-correct variants are present. The public
`PPPP_*` core exports did not disappear. The old and current binaries expose
the same 26 identified JNI wrappers; no changed Java native method is required
for initialize/connect/check/read/write compatibility.

The static API-version proof follows the branch from `PPPP_GetAPIVersion` to
`PPPP_Get_APIVersion` and decodes the AArch64 immediate construction as
`0xA2050401`. It makes no transport call and does not initialize PPPP.

## Evidence classification

```text
current native library present: CURRENT_CLIENT_PROVEN
current architecture: CURRENT_CLIENT_PROVEN
current SHA/size/exports/dependencies: CURRENT_CLIENT_PROVEN
current PPPP API version 0xA2050401: CURRENT_CLIENT_PROVEN
runtime-selected newP2PStrategy: UNKNOWN
runtime effect on POOL: UNKNOWN
```
