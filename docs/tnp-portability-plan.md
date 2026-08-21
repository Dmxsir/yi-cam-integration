# YI TNP portability plan

This is a design boundary, not a Phase 2D implementation. The stock native Yi
library is a behavioral oracle only. A future portable client must not depend
on redistributing `PPPP_API.dll` or `libPPPP_API.so`.

## Layered target

```text
YI cloud discovery
    ↓
Yi TNP credential acquisition
    ↓
portable PPPP transport
    ↓
Yi-specific PPPP/session layer
    ↓
TNP authentication
    ↓
TNP channel framing
    ↓
video decryption
    ↓
H.264/H.265 elementary stream reconstruction
    ↓
streaming adapter
    ↓
go2rtc / Frigate
```

The last two layers are explicitly outside Phase 2C.

## Layer contracts and current evidence

| Layer | Minimal input/output contract | Current evidence | Remaining gate |
|---|---|---|---|
| YI cloud discovery | Credentials + explicit app metadata in memory -> sanitized camera records and live auth state | `LIVE_CLOUD_PROVEN` for EU/IL | Keep tokens and passwords memory-only; preserve tolerant production schema validation. |
| TNP credential acquisition | Selected cloud UID + live auth -> DID, InitString, first License component, camera password, `p2p_encrypt`, wakeup | `LIVE_CLOUD_PROVEN` for the selected y291ga | Re-fetch for every selected camera; never persist secret material. |
| Portable PPPP transport | DID/server/license key -> bidirectional reliable logical channels and connection-mode metadata | Proprietary oracle achieved direct P2P in production; portable wire format is `UNKNOWN` | Secret-safe transport capture and independent Yi-fork reimplementation are required. |
| Yi PPPP/session policy | Target metadata -> exact init/connect/wakeup/relay policy | `APK_PROVEN`; direct `PPPP_Connect` flag `0x4B` and mode 0 were `LIVE_CAMERA_PROVEN` | Establish how current Yi transport differs from generic F1/F2 descriptions. |
| TNP authentication | Camera password + session state -> authenticated channel-0 command/response | HMAC/nonce algorithm is `APK_PROVEN` and `YI_DEVICE_SOURCE_CORROBORATED` | Current y291ga closed after the first command without a response; resolve this boundary before continuing. |
| TNP channel framing | PPPP channel bytes -> complete 8-byte-head application units | 8/40/24-byte layouts are `APK_PROVEN` and corroborated | No inbound production unit was received. |
| Video decryption | Encrypted I payload + in-memory key -> original compressed payload | Two-block AES behavior is `APK_PROVEN` and corroborated | Obtain a live encrypted I-frame and prove valid NAL framing after decryption. |
| Elementary-stream reconstruction | Parsed ordered frames -> unchanged `.h264` or `.h265` stream | Analyzer and offline fixtures exist | Prove codec, sequence/timestamp ordering, SPS/PPS/VPS behavior, and decoder acceptance live. |
| Streaming adapter | Elementary access units -> downstream framed stream | Not started | Phase 2D only, after the native protocol proof succeeds. |

## Portable interfaces

Keep interfaces narrow and secret-aware:

```text
CloudSession.login(config, credentials) -> in-memory auth state
CloudSession.devices() -> sanitized Device records
CloudSession.tnp_info(device) -> SecretTnpMaterial

PpppTransport.connect(SecretTnpMaterial, policy) -> ChannelSession
ChannelSession.read(channel, exact_length, timeout) -> bytes
ChannelSession.write(channel, bytes) -> count
ChannelSession.check() -> mode/timing metadata

TnpSession.authenticate_and_command(command, payload) -> response
TnpSession.frames(channel) -> TnpVideoUnit
VideoDecryptor.decrypt_iframe(unit, secret_key) -> compressed payload
ElementaryWriter.write_ordered(units) -> codec-specific byte stream
```

`SecretTnpMaterial` must be non-serializable by default, must redact its
representation, and should clear mutable buffers on teardown. Diagnostics may
record availability, lengths, status codes, channels, and byte counts, never
secret values or authenticated URLs.

## What public projects can and cannot inform

| Concept | Candidate reference | Portability decision |
|---|---|---|
| Async UDP lifecycle, retransmission organization, channel queues | [`devbis/aiopppp`](https://github.com/devbis/aiopppp), Apache-2.0 | Potentially reusable concepts or code after an explicit compatibility review. Its tested A9/X5 commands and credentials must not be imported as Yi behavior. |
| Packet classification and Wireshark workflow | [`magicus/pppp-dissector`](https://github.com/magicus/pppp-dissector), MIT | Potential tooling base for a future sanitized capture. Verify Yi packet differences before decoding. |
| Static/dynamic/packet-capture workflow | [`DavidVentura/cam-reverse`](https://github.com/DavidVentura/cam-reverse) | Methodology only unless licensing and exact reused material are reviewed. |
| Yi TNP application semantics | [`frankzhangshcn/p2p_tnp`](https://github.com/frankzhangshcn/p2p_tnp) | Evidence only. No repository license was found, so no source reuse. Independently implement from the APK/live contract. |
| Yi model and firmware corroboration | [`roleoroleo/yi-hack-Allwinner-v2`](https://github.com/roleoroleo/yi-hack-Allwinner-v2), MIT | Documentation/model evidence only; modified firmware is not part of the solution. |
| Proprietary transport behavior | APK `libPPPP_API.so` | Oracle-only. Do not redistribute or make it the production runtime. |

Generic PPPP and Yi TNP remain separate namespaces. In particular,
`pppp_transport_header_variant` (for example research labels F1/F2) must not be
derived from `tnp_application_version`.

## Evidence-driven implementation order

1. Resolve the current first-command boundary with the official-client state
   reproduced exactly and with the same one-attempt safety discipline.
2. Obtain a secret-safe application trace proving the peer TNP version, auth
   result, command 9029, and channels 2/3.
3. Validate 8/24/40-byte layouts, codec, NAL framing, encryption offsets, and
   SPS/PPS/VPS behavior against multiple I-frames.
4. Reconstruct and decode the original elementary stream without transcoding.
5. Capture only the minimum transport metadata needed to distinguish the Yi
   PPPP variant; avoid a PCAP if it would retain DID, InitString, license, or
   other forbidden values.
6. Write portable PPPP transport tests from sanitized packet metadata and
   independently specified state transitions.
7. Replace the proprietary oracle one layer at a time while comparing return
   codes, channel behavior, retransmission, and teardown.
8. Only after parity, design the downstream streaming adapter in Phase 2D.

## Test strategy

- Keep cloud, transport, TNP, crypto, and video fixtures separate.
- Generate nonce/HMAC fixtures from fake passwords; never capture a live
  authentication header in a committed fixture.
- Use synthetic headers and NAL units for unit tests.
- Store live raw frames only under ignored `captures/`, after checking that no
  in-memory secret byte sequence occurs in a record.
- Require ffprobe and full ffmpeg decode for a future live elementary stream,
  but never treat decoder success as a substitute for protocol validation.
- Test teardown on success, timeout, remote close, and malformed response.

## Current stop condition

Phase 2C has not met its success condition. Production cloud material and a
direct PPPP session were proven, but the selected y291ga closed the connection
after the first channel-0 command and before an authenticated response. Command
9029, video channels, decryption, reconstruction, and decoder validation remain
unreached. No production bridge or streaming integration should begin from
this state.
