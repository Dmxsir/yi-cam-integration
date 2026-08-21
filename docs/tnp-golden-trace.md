# Current official-client golden TNP trace

## Outcome

```text
approved target: POOL / model 83 / y291ga / type 2
current installed client: 6.9.7_20260820043046 / 453 / ARM64
official current Live View: SUCCESS
connection: UDP DIRECT_P2P to 10.0.0.150
outer TNP application version: 2
first command: 9031 / TNP event-list request
first TNP packet: 72 bytes
custom oracle retry: NOT RUN
```

This is `PCAP_RUNTIME_PROVEN` from the official stock application. The trace
was obtained without root, TLS interception, app modification, private app
storage, or Java/native instrumentation. Raw authenticated packets remain
only under ignored `captures/`; this document contains structural metadata.

## Proven framing

The successful current session uses the same framing established statically:

| Layer | Current runtime value | 2022 comparison |
|---|---|---|
| Outer TNP header | 8 bytes | `MATCH` |
| application version | 2 | `MATCH` |
| IO/stream type for commands | 3 | `MATCH` |
| outer reserved bytes | zero | `MATCH` |
| outer data size | big-endian at offset 4 | `MATCH` |
| IOCTRL header | 40 bytes | `MATCH` |
| command/number/extra/payload sizes | four big-endian 16-bit fields | `MATCH` |
| authInfo field | 32 bytes | `MATCH` |
| actual authInfo | 31 bytes plus zero | `MATCH` |
| nonce/HMAC component lengths | 15 / 15 | `MATCH` |

No authentication contents were compared or retained. The runtime shape is
consistent with the statically proven 7-character session nonce plus
8-character command suffix, comma, and 15 retained Base64 HMAC characters.

The critical correction is that the observed outer bytes begin `02 03`:
`TNPHead` assigns byte 0 to application version and byte 1 to IO type. Both
current and older successful official sessions therefore use TNP v2.

## First five writes and reads

Times are relative to the first official channel-0 write. Seven writes at
3.028 ms are distinct TNP units batched into one DRW sequence-1 packet.

### First five writes

| Order | T+ ms | DRW seq/batch | command | no. | total | payload |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 0.000 | 0/0 | 9031 | 1 | 72 | 24 |
| 2 | 3.028 | 1/0 | 9029 | 2 | 52 | 4 |
| 3 | 3.028 | 1/1 | 768 | 3 | 56 | 8 |
| 4 | 3.028 | 1/2 | 769 | 4 | 56 | 8 |
| 5 | 3.028 | 1/3 | 767 | 5 | 56 | 8 |

The remainder of the same startup DRW is 12718/no.6, 849/no.7, and 816/no.8.
The 9029 fixed payload is `01 01 01 00`. The 768/769/767/849 payloads are
eight zero/reserved bytes.

### First five reads/responses

| Order | T+ ms | DRW seq | command | no. | total | payload |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 326.915 | 0–5 | 9032 | 1 | 5724 | 5676 |
| 2 | 327.091 | 6 | 4882 | 65535 | 56 | 8 |
| 3 | 327.308 | 7 | 817 | 8 | 392 | 344 |
| 4 | 404.132 | 8–13 | 9032 | 9 | 5724 | 5676 |
| 5 | 1360.755 | 14–19 | 9032 | 10 | 5724 | 5676 |

The first 9032 body spans six DRW messages, proving why one UDP datagram cannot
be treated as one application message.

## Current startup state machine

The exact observed order is:

```text
9031
  3.028 ms later:
  9029 -> 768 -> 769 -> 767 -> 12718 -> 849 -> 816

9032 -> unsolicited/status 4882 -> 817

event-list refreshes

5928.507 ms:
  9029 -> 768
```

9031/9032 are the TNP event-list request/response. Current static code traces
the request through `com.xiaoyi.yiplayer.f.J0()` to
`CameraCommandHelper.getEvents()`/`getTnpEvents()`, and constructs its 24-byte
payload with `SMsgAVIoctrlListEventReq`. The runtime proves this timeline path
was queued before live start. The precise UI scheduler reason is `INFERRED`,
not statically proven.

The second 9029 payload is `02 01 01 00`. One 1920×1080 I-frame with use-count
1 follows the first request; continuous channel-3 video, channel-1 audio, and
use-count-2 frames follow the second request. This supports an initial
I-frame/preload subscription followed by foreground live playback, but that
UI label remains `LIKELY`.

## Cross-client result

The older official capture starts differently but uses identical TNP v2 and
header/auth layout:

```text
4881 -> 9029 -> 768        (one DRW at T+0)
816 -> 12718 -> 9029       (one DRW at T+107.207 ms)
4864 -> 9031               (one DRW at T+200.606 ms)
```

Its camera returns 4882 at 34.209 ms and media begins by 80.793 ms. Therefore
4881 is valid as the first application command on production y291ga, but the
failed oracle's stop-and-wait behavior did not reproduce the successful
official startup burst.

The complete per-command timelines, channel statistics, and transport
comparison are in `docs/tnp-network-golden-trace.md`.
