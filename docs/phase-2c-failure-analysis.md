# Phase 2C `-3012` A/B failure analysis

## Established cases

The comparison now has a successful first-command control case from the same
model family:

| Property | Current 6.9.7 / POOL | Older official / POOL | Failed custom oracle |
|---|---|---|---|
| Result | Live View success | Live View success | remote close, no response |
| client/API | 6.9.7; PPPP `0xA2050401` | exact version/API `UNKNOWN` | PPPP `0xA2030401` |
| transport | UDP direct P2P | UDP direct P2P | direct P2P |
| first command | 9031 | 4881 | 4881 |
| first TNP size | 72 | 56 | 56 |
| TNP application version | 2 | 2 | 2 |
| first application group | 9031 alone | 4881 + 9029 + 768 | 4881 then blocking read |
| first response | 9032 at 326.915 ms | 4882 at 34.209 ms | none; `-3012` after about 11 s |
| target | POOL/y291ga | POOL/y291ga | another model-83/y291ga camera |

The old oracle event log proves its transmitted version was 2, not an
assumption from source defaults. It also proves channel 0, command 4881,
command number 1, 56 bytes, and a successful 56-byte `PPPP_Write`.

## Successful 4881 versus failed 4881

No secret bytes are compared. The official auth field is reduced to lengths
and termination, and the oracle side is established from its builder plus its
sanitized runtime configuration/event record.

| Field | Older official success | Failed oracle | Result |
|---|---|---|---|
| native application channel | 0 | 0 | `MATCH` |
| wire DRW layout | CS2-base Yi DRW | no oracle PCAP | `UNKNOWN` |
| wire DRW sequence | 0 | native-assigned, not captured | `UNKNOWN` |
| TNP total | 56 | 56 | `MATCH` |
| outer header size | 8 | 8 | `MATCH` |
| TNP application version | 2 | 2 | `MATCH` |
| IO/stream type | 3 | 3 | `MATCH` |
| outer reserved bytes | zero | zero-initialized | `MATCH` |
| `nDataSize` | 48, big-endian | 48, big-endian | `MATCH` |
| IOCTRL header | 40 | 40 | `MATCH` |
| command | 4881 | 4881 | `MATCH` |
| command number | 1 | 1 | `MATCH` |
| extra-header size | 0 | 0 | `MATCH` |
| payload size | 8 | 8 | `MATCH` |
| payload resolution | 2 | 2 | `MATCH` |
| payload use-count | 1 | 1 | `MATCH` |
| field byte order | big-endian | big-endian | `MATCH` |
| authInfo field capacity | 32 | 32 | `MATCH` |
| actual encoded authInfo | 31 | 31 | `MATCH` |
| nonce structural length | 15 | 15 | `MATCH` |
| retained HMAC/Base64 component | 15 | 15 | `MATCH` |
| zero termination | yes, final byte | yes, zero-initialized remainder | `MATCH` |
| auth contents/HMAC correctness | deliberately not retained | deliberately not retained | `UNKNOWN` |
| surrounding first DRW | three TNP units, 164 application bytes | only one write issued before wait | `DIFFERENT` |
| response handling | reader and startup continue | blocking read immediately after 4881 | `DIFFERENT` |

The successful official 4882/no.1 has a zero auth-result field and arrives at
34.209 ms. This proves production y291ga accepts a first 4881 with exactly the
same visible TNP structure as the oracle. It does not prove the oracle's secret
HMAC content or native wire framing matched.

## Immediate-burst finding

The successful older client sends, in one DRW sequence-0 packet at T+0:

```text
4881/no.1, resolution=2, use-count=1
9029/no.2, payload 02 02 01 00
768/no.3, eight zero bytes
```

All three precede the first 4882 at 34.209 ms. The failed oracle wrote only
4881 and then synchronously waited. The behavioral difference is
`PCAP_RUNTIME_PROVEN`; its causal classification is `STRONG_CANDIDATE`, not
`CONFIRMED_CAUSE`.

It is plausible that back-to-back `PPPP_Write` calls allow the official native
library to coalesce the three TNP units into one DRW message or otherwise
advance a camera-side startup state before a response is expected. No failed-
oracle wire PCAP exists, so exact DRW framing and sequence remain unknown.

## Root-cause ranking

There is still no single confirmed cause. Rankings distinguish proven parity
from unobserved secret/native state.

| Candidate | Classification | Reason |
|---|---|---|
| application state-machine mismatch | `STRONG_CANDIDATE` | Official older success sends a multi-command startup group; oracle stops after packet one. |
| waiting after 4881 / missing immediate 9029+768 | `STRONG_CANDIDATE` | Concrete successful-versus-failed behavioral difference before the first response. |
| timing/coalescing behavior | `LIKELY` | Official first three units share one D0 at one capture timestamp; oracle cannot form that group after blocking. |
| DRW framing mismatch | `POSSIBLE` | Oracle wire framing was never captured; zero response is compatible with failure before IOCTRL dispatch. |
| old PPPP native generation/session semantics | `POSSIBLE` | Current API is `0xA2050401`, oracle is `0xA2030401`; Capture B's exact native API remains unknown. |
| PPPP initializer strategy | `POSSIBLE` | Oracle used one zero byte; production settings/library behavior for Capture B are unavailable. |
| connect flag | `POSSIBLE` | Oracle used `0x4B`; Capture B's flag cannot be recovered from PCAP. |
| wrong nonce/session or HMAC content | `POSSIBLE` | Structural auth matches, but secret content is intentionally not compared and the failed target was a different camera. |
| invalid recovered camera password | `POSSIBLE` | No auth-result response was received; neither confirmed nor ruled out. |
| DRW sequence mismatch | `POSSIBLE` | Official begins at sequence 0; oracle sequence is native-assigned and unobserved. |
| malformed outer/IOCTRL layout | `RULED_OUT` for visible fields | Sizes, offsets, byte order, version, reserved fields, and total all match. |
| malformed 4881 payload | `RULED_OUT` | Resolution 2/use-count 1 exactly matches the official success case. |
| wrong TNP application version | `RULED_OUT` | Both successful captures and the failed oracle use version 2. |
| authInfo structural mismatch | `RULED_OUT` | Capacity, encoded/component lengths, comma shape, and zero termination match. |
| 4881 cannot be first | `RULED_OUT` | Capture B starts with 4881 and receives successful 4882/no.1. |

The strongest explanation is therefore an application-state/timing mismatch,
but the primary `-3012` cause remains formally `UNKNOWN`. A pre-dispatch DRW or
native-session difference is the second strongest family of explanations.

## Smallest evidence-backed next test — design only

`READY_FOR_CUSTOM_RETRY = YES`, but this phase does **not** execute it.

The recommended reference is `OLDER_OFFICIAL`: it is the smallest successful
y291ga sequence and avoids the current client's event-history commands.

The one future test should keep the old native library, initializer, connect
flag, TNP v2, auth builder, resolution, and 4881 bytes unchanged so that only
the proven behavioral discrepancy changes:

1. Start channel-0 response reading before or concurrently with startup; do
   not issue a blocking read between writes.
2. Write 4881/no.1, 56 bytes, resolution 2/use-count 1.
3. Immediately write 9029/no.2, 52 bytes, payload `02 02 01 00`.
4. Immediately write 768/no.3, 56 bytes, eight zero payload bytes.
5. Then process responses. The minimal success criterion is a structurally
   valid 4882 with auth result zero; media proof is a later step.

No fixed inter-command sleep should be introduced: the official units occupy
one DRW at the same timestamp. Native `PPPP_Write` remains responsible for DRW
framing; the oracle must not handcraft it. If a future secret-safe PCAP shows
that the three immediate writes are not grouped or sequenced like the official
capture, stop and treat that as new transport evidence rather than guessing.

The next test should not change to the current native library at the same time,
because that would combine two hypotheses. If the corrected three-command
state machine still yields zero bytes and `-3012`, the next investigation
should capture its wire shape and then evaluate the native/API,
initializer/connect-flag, or credential-state candidates.

No custom connection was made while producing this analysis.
