# Phase 2C controlled production report

## Required result matrix

```text
selected camera:
    מחסן

raw model:
    83

normalized model:
    y291ga

cloud online:
    CONFIRMED immediately before test

DID:
    AVAILABLE

InitString:
    AVAILABLE

License/device key:
    AVAILABLE

camera password:
    AVAILABLE

p2p_encrypt:
    true

oracle platform:
    ANDROID

native Yi library:
    identified

PPPP initialization:
    SUCCESS

PPPP connection:
    SUCCESS

connection mode:
    P2P

TNP authentication:
    FAIL

PPPP transport header variant:
    UNKNOWN

TNP application version:
    UNKNOWN

realtime command 9029:
    FAIL

realtime 4-byte payload:
    FAIL

channel 2:
    no traffic observed

channel 3:
    no traffic observed

codec:
    UNKNOWN

resolution:
    UNKNOWN

frame format:
    UNKNOWN

SPS:
    UNKNOWN

PPS:
    UNKNOWN

VPS:
    UNKNOWN

encryption algorithm:
    UNKNOWN live; AES-128 two independent blocks is APK_PROVEN and YI_DEVICE_SOURCE_CORROBORATED

I-frame decryption:
    FAIL

reconstructed elementary stream:
    FAIL

ffprobe:
    FAIL

ffmpeg decode:
    FAIL

clean shutdown:
    FAIL
```

`TNP authentication: FAIL` means that an authenticated response was not
obtained. It does not assert that a bad-password result was returned: the peer
sent no TNP response bytes and closed the PPPP session remotely (`-3012`). The
client-sent provisional application version 2 is not reported as the observed
peer version.

## Live milestones and evidence classes

| Milestone | Result | Evidence class |
|---|---|---|
| Production EU/IL login, discovery, and TNP info | Success | `LIVE_CLOUD_PROVEN` |
| Primary target still online/model 83/y291ga/type 2 | Confirmed | `LIVE_CLOUD_PROVEN` |
| Required TNP material and recovered password | Available in memory | `LIVE_CLOUD_PROVEN` |
| Untouched Yi ARM64 library loaded under Android translation | Success | Live native-oracle observation |
| PPPP init/connect/check | Success | `LIVE_CAMERA_PROVEN` |
| Direct P2P mode | Mode 0 | `LIVE_CAMERA_PROVEN` |
| First channel-0 write | Native accepted 56 bytes | Live native API observation |
| First channel-0 response | Remote close, zero bytes | `LIVE_CAMERA_PROVEN` failure boundary |
| TNP authentication response | Not obtained | `UNKNOWN` reason / failed milestone |
| Command 9029 and video | Not reached | `UNKNOWN` |
| Normal application stop/deinit proof | Not reached | Failed milestone; isolated process was force-stopped |

The exact cross-source comparison and unresolved discrepancy are in
[tnp-crosscheck.md](tnp-crosscheck.md). The production-independent next-layer
design is in [tnp-portability-plan.md](tnp-portability-plan.md).
