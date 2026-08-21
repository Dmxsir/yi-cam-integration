# Phase 2C.2 dual official network golden trace

## Result and evidence boundary

Two PCAPdroid captures from the same `POOL` camera (`10.0.0.150`, raw model
83, normalized `y291ga`, cloud type 2/TNP) were decoded independently. No
custom oracle connection was made.

Evidence labels in this document are:

- `PCAP_RUNTIME_PROVEN`: decoded from one of the supplied official sessions.
- `CURRENT_APK_PROVEN`: present in the installed 6.9.7 APK set.
- `OLD_APK_PROVEN`: present in the analyzed 5.6.5 APK, without claiming that
  Capture B ran that exact release.
- `INFERRED`: best explanation consistent with the runtime and static data.
- `UNKNOWN`: not established by the available artifacts.

The preliminary claim that both captures used TNP version 3 was incorrect.
Both use **TNP application version 2**. `TNPHead` defines byte 0 as version and
byte 1 as IO/stream type; the observed prefix is therefore `version=2,
ioType=3`, not version 3.

| Capture | Official client | Bytes | SHA-256 |
|---|---|---:|---|
| A | `6.9.7_20260820043046` / 453 / ARM64 | 3,792,474 | `C7660100F69B3B650B41DCCE32C46CEB4EF59FF9CEB32B9241DE364C02F81C34` |
| B | `OLD_CLIENT_VERSION = UNKNOWN` | 1,688,317 | `68CD99A5AA38DFB0D3A11E772BD0EE6EACE42DDE932970A80C242295C3261561` |

The exact Capture B version cannot be derived from the PCAP. The project has a
5.6.5 APK, but there is no evidence tying that file to the installed app that
made Capture B.

Both raw captures and their sanitized reports are under ignored `captures/`.
`.gitignore` covers that whole directory. The decoder never returns raw TNP
units, authInfo, nonce, HMAC, credentials, or media bytes.

## Decoder behavior

`tools/yi_pppp_pcap.py` parses classic PCAP and PCAPNG, IP/UDP/TCP, multiple
PPPP messages in a transport payload, and the Yi/CS2 envelopes relevant here:

| Envelope | Decoded meaning |
|---|---|
| `F1 D0` | `MSG_DRW` |
| `F1 D1` | `MSG_DRW_ACK` |
| `F1 E0` | alive |
| `F1 E1` | alive acknowledgement |
| `F1 F0` | close |

It de-duplicates exact D0 retransmissions, orders each direction/channel by
DRW sequence, reassembles TNP units split across messages, and separates
multiple complete TNP units batched in one DRW application body. Both supplied
captures finish with zero incomplete bytes and zero malformed reassembled TNP
units.

For channel 0 it validates the eight-byte outer TNP header, 40-byte IOCTRL
header, optional extra header, payload length, and 32-byte auth field. Only the
auth field capacity, actual encoded length, two component lengths, and
zero-termination state survive into the report.

## Connection mode

Both official sessions are direct local UDP, not relay sessions:

| Capture | Phone-side VPN address/port | Camera peer | Result |
|---|---|---|---|
| A | `10.215.173.1:23808` | `10.0.0.150:10236` | `DIRECT_P2P` |
| B | `10.215.173.1:17970` | `10.0.0.150:12921` | `DIRECT_P2P` |

The PCAPdroid VPNService address is visible on the phone side, but packets
still demonstrably reach the camera's private LAN address directly. The
capture environment did not force a cloud relay.

## Capture A — current 6.9.7

All entries below are reassembled channel-0 TNP units carried by `F1 D0`.
Times are relative to the first phone command. `batch` is the zero-based TNP
unit inside the same DRW message.

| T+ ms | Direction | DRW seq | batch | TNP v | Command | no. | TNP bytes | payload |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 0.000 | phone→camera | 0 | 0 | 2 | 9031 | 1 | 72 | 24 |
| 3.028 | phone→camera | 1 | 0 | 2 | 9029 | 2 | 52 | 4 |
| 3.028 | phone→camera | 1 | 1 | 2 | 768 | 3 | 56 | 8 |
| 3.028 | phone→camera | 1 | 2 | 2 | 769 | 4 | 56 | 8 |
| 3.028 | phone→camera | 1 | 3 | 2 | 767 | 5 | 56 | 8 |
| 3.028 | phone→camera | 1 | 4 | 2 | 12718 | 6 | 72 | 24 |
| 3.028 | phone→camera | 1 | 5 | 2 | 849 | 7 | 56 | 8 |
| 3.028 | phone→camera | 1 | 6 | 2 | 816 | 8 | 52 | 4 |
| 326.915 | camera→phone | 0–5 | 0 | 2 | 9032 | 1 | 5724 | 5676 |
| 327.091 | camera→phone | 6 | 0 | 2 | 4882 | 65535 | 56 | 8 |
| 327.308 | camera→phone | 7 | 0 | 2 | 817 | 8 | 392 | 344 |
| 391.353 | phone→camera | 2 | 0 | 2 | 9031 | 9 | 72 | 24 |
| 404.132 | camera→phone | 8–13 | 0 | 2 | 9032 | 9 | 5724 | 5676 |
| 1352.598 | phone→camera | 3 | 0 | 2 | 9031 | 10 | 72 | 24 |
| 1360.755 | camera→phone | 14–19 | 0 | 2 | 9032 | 10 | 5724 | 5676 |
| 5928.507 | phone→camera | 4 | 0 | 2 | 9029 | 11 | 52 | 4 |
| 5928.507 | phone→camera | 4 | 1 | 2 | 768 | 12 | 56 | 8 |
| 5953.415 | camera→phone | 20 | 0 | 2 | 4882 | 65535 | 56 | 8 |
| 6043.140 | phone→camera | 5 | 0 | 2 | 816 | 13 | 52 | 4 |
| 6065.449 | camera→phone | 21 | 0 | 2 | 817 | 13 | 392 | 344 |
| 6140.781 | phone→camera | 6 | 0 | 2 | 9031 | 14 | 72 | 24 |
| 6153.986 | camera→phone | 22–27 | 0 | 2 | 9032 | 14 | 5724 | 5676 |
| 7150.669 | phone→camera | 7 | 0 | 2 | 9031 | 15 | 72 | 24 |
| 7166.753 | camera→phone | 28–33 | 0 | 2 | 9032 | 15 | 5724 | 5676 |
| 20327.961 | phone→camera | 8 | 0 | 2 | 769 | 16 | 56 | 8 |
| 20327.961 | phone→camera | 8 | 1 | 2 | 768 | 17 | 56 | 8 |
| 20327.961 | phone→camera | 8 | 2 | 2 | 767 | 18 | 56 | 8 |
| 20327.961 | phone→camera | 8 | 3 | 2 | 12718 | 19 | 72 | 24 |
| 20431.108 | phone→camera | 9 | 0 | 2 | 849 | 20 | 56 | 8 |

The first 9031 is one 80-byte PPPP message containing one 72-byte TNP unit.
The seven units at 3.028 ms are one 408-byte PPPP message whose DRW application
body contains 400 TNP bytes. Thus the corrected startup order is exactly:

```text
9031
  -> 9029 -> 768 -> 769 -> 767 -> 12718 -> 849 -> 816
```

The first 9029 payload is `01 01 01 00`; the second is `02 01 01 00`.
The four fields are `use_count`, `resolution`, literal command version 1, and
reserved zero (`CURRENT_APK_PROVEN`, `OLD_APK_PROVEN`, and
`PCAP_RUNTIME_PROVEN`).

## Capture B — older official client

| T+ ms | Direction | DRW seq | batch | TNP v | Command | no. | TNP bytes | payload |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 0.000 | phone→camera | 0 | 0 | 2 | 4881 | 1 | 56 | 8 |
| 0.000 | phone→camera | 0 | 1 | 2 | 9029 | 2 | 52 | 4 |
| 0.000 | phone→camera | 0 | 2 | 2 | 768 | 3 | 56 | 8 |
| 34.209 | camera→phone | 0 | 0 | 2 | 4882 | 1 | 56 | 8 |
| 34.209 | camera→phone | 0 | 1 | 2 | 4882 | 65535 | 56 | 8 |
| 107.207 | phone→camera | 1 | 0 | 2 | 816 | 4 | 52 | 4 |
| 107.207 | phone→camera | 1 | 1 | 2 | 12718 | 5 | 72 | 24 |
| 107.207 | phone→camera | 1 | 2 | 2 | 9029 | 6 | 52 | 4 |
| 135.594 | camera→phone | 1 | 0 | 2 | 817 | 4 | 392 | 344 |
| 173.050 | camera→phone | 2 | 0 | 2 | 4882 | 65535 | 56 | 8 |
| 200.606 | phone→camera | 2 | 0 | 2 | 4864 | 7 | 52 | 4 |
| 200.606 | phone→camera | 2 | 1 | 2 | 9031 | 8 | 72 | 24 |
| 224.075 | camera→phone | 3 | 0 | 2 | 4865 | 7 | 70 | 22 |
| 234.250 | camera→phone | 4–9 | 0 | 2 | 9032 | 8 | 5736 | 5688 |
| 1161.728 | phone→camera | 3 | 0 | 2 | 9031 | 9 | 72 | 24 |
| 1180.664 | camera→phone | 10–15 | 0 | 2 | 9032 | 9 | 5736 | 5688 |
| 25127.471 | phone→camera | 4 | 0 | 2 | 769 | 10 | 56 | 8 |
| 25127.471 | phone→camera | 4 | 1 | 2 | 768 | 11 | 56 | 8 |
| 25127.471 | phone→camera | 4 | 2 | 2 | 767 | 12 | 56 | 8 |
| 25127.471 | phone→camera | 4 | 3 | 2 | 12718 | 13 | 72 | 24 |
| 25178.502 | phone→camera | 5 | 0 | 2 | 849 | 14 | 56 | 8 |

The initial 4881, 9029, and 768 are three complete TNP units in **one** DRW
sequence-0 packet: 164 application bytes and 172 bytes including DRW/PPPP
framing. All three are sent before the first 4882 response at 34.209 ms.

The 4881 payload is resolution 2/use-count 1. The first 9029 is
`02 02 01 00`; the second is `03 02 01 00`. The 768 payload is eight zero
bytes, matching both old and current `TnpCamera.sendStartListeningCommand()`.

## Command meanings

| ID | Symbolic meaning | Static evidence | Runtime evidence |
|---:|---|---|---|
| 767 | `IOTYPE_USER_IPCAM_STOP` (stop video) | current + old APK | both captures |
| 768 | `IOTYPE_USER_IPCAM_AUDIOSTART` | current + old APK | both captures |
| 769 | `IOTYPE_USER_IPCAM_AUDIOSTOP` | current + old APK | both captures |
| 816/817 | device-info request/response | current + old APK | both captures |
| 849 | speaker stop | current + old APK | both captures |
| 4864/4865 | update/check-phone request/response | current + old APK | Capture B |
| 4881/4882 | set-resolution request/response | current + old APK | both captures |
| 9029 | TNP start realtime | current + old APK | both captures |
| 9031/9032 | TNP event-list request/response | current + old APK | both captures |
| 12718 | encrypted record-play control (`RECORD_PLAYCONTROL2`) | current + old APK | both captures |

9031 is not named from numeric adjacency. `CameraCommandHelper.getEvents()`
selects `getTnpEvents()` for type 2 and constructs 9031 with
`SMsgAVIoctrlListEventReq.parseConent(...)`; the expected response is 9032 and
is parsed by `SMsgAVIoctrlTnpListEventResp`. Its 24-byte request is channel (4),
start UTC (8), end UTC (8), event type (1), status (1), and reserved (2). No
values from these fields are retained.

The current player has an event/timeline request path through
`com.xiaoyi.yiplayer.f.J0(long,long)`. Capture A proves that this request won
the runtime queue before realtime start. The most specific safe explanation
is that the current timeline/event initialization executes first in this UI
session (`INFERRED`); the decompiled code does not prove scheduler timing.
Capture B proves its older client deferred the same event request until
200.606 ms. Why that older UI scheduled it later is `UNKNOWN`, particularly
because its exact app version is unknown.

## Video/audio timing and 9029 correlation

Times are relative to the first channel-0 phone command.

| Capture | First ch.2 | First ch.1 | First ch.3 | Frame structure |
|---|---:|---:|---:|---|
| A/current | 327.111 ms | 5988.542 ms | 6008.919 ms | H.264 codec id 78, 1920×1080 |
| B/older | 80.793 ms | 97.374 ms | 110.535 ms | H.264 codec id 78, 640×360 |

Capture A has six reassembled channel-2 video units: one I-frame with
use-count 1 after the first 9029, then five units with use-count 2 beginning at
5972.339 ms. The second 9029 occurs at 5928.507 ms; channel 1 begins 60.035 ms
and channel 3 begins 80.412 ms later. Channel 3 contains 295 decoded frame
units, all use-count 2. The first subscription therefore behaves like an
initial/preload I-frame request and the second like the foreground continuous
stream (`LIKELY`, not a proven UI semantic).

Capture B begins channel 2, audio, and channel 3 within 111 ms of the initial
burst. Its first stream units use count 2. The second 9029 at 107.207 ms raises
the count to 3; use-count-3 channel-2 frames begin at 225.701 ms and
use-count-3 channel-3 frames at 265.809 ms. This confirms byte 0 behaves as a
subscription/use counter. Resolution byte 1 is 1 in Capture A and 2 in B,
matching their 1920×1080 and 640×360 frame metadata respectively. The reason
for the different selected quality is client/session preference (`UNKNOWN`),
not a TNP-version change.

No media payload was decrypted, reconstructed, or persisted.

## PPPP transport comparison

| Property | A/current | B/older |
|---|---:|---:|
| D0 wire messages | 993 | 2563 |
| D1 ACK messages | 558 | 833 |
| exact D0 retransmissions | 7 | 1503 |
| E0 alive messages | 119 | 188 |
| E1 alive ACK messages | 100 | 188 |
| F0 close | not captured | not captured |

Capture A phone→peer E0 messages all have a four-byte payload with structural
value `0xA2050400`; peer→phone E0 is four bytes with `0xD2040200`. Capture B
phone→peer E0 is zero length (137 messages), while peer→phone E0 is four bytes
with `0xD2040200` (51 messages). The current library API is `0xA2050401`, so
the current alive field shares its high 24 bits but is not equal. Treating the
field as the exact API version would be unsupported; its semantics remain
`UNKNOWN`.

The large Capture B retransmission count and different DRW/ACK distribution
prove transport-generation behavior differs. They do not by themselves prove
loss or a defect, because capture duration, media bitrate, and ACK batching
also differ.

## Reproduction commands and tests

```powershell
python tools\yi_pppp_pcap.py captures\pool-official-golden.pcap `
  --phone-ip 10.215.173.1 `
  --output captures\pool-official-golden.sanitized.json

python tools\yi_pppp_pcap.py captures\pool-older-official-golden.pcap `
  --phone-ip 10.215.173.1 `
  --output captures\pool-older-official-golden.sanitized.json
```

Synthetic tests cover 4881/56, 9029/52, 9031/72, TNP v3 parser tolerance,
multi-unit DRW batching, split and out-of-capture-order sequence reassembly,
channels 1/2/3, alive/close classification, zero reserved payloads, and secret
non-disclosure. Real authenticated packets are not committed as fixtures.
