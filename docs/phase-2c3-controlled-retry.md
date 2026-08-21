# Phase 2C.3 — Controlled startup-burst retry

## Scope

This phase changes exactly one behavior relative to the failed Phase 2C oracle: the application startup sequence no longer blocks for a channel-0 response after command `4881`.

The reference is the successful older official YI Home PCAP against `POOL` (`model 83 / y291ga`).

Runtime-proven official startup:

1. `4881` — set resolution, 56-byte TNP unit.
2. `9029` — realtime start with payload `02 02 01 00`, 52-byte TNP unit.
3. `768` — eight-zero-byte payload.
4. Only then process channel-0 responses.

The successful official client received `4882` roughly 34 ms after the first request and video channels followed shortly afterwards.

## Frozen variables

The controlled retry intentionally keeps the previous oracle's transport/native variables unchanged:

- PPPP native library generation.
- `PPPP_Initialize(new byte[] {0}, 12)`.
- connection flag `0x4B`.
- TNP application version `2`.
- authentication algorithm and nonce layout.
- one stable seven-character session nonce with a fresh eight-character command nonce per IOCTRL.
- resolution `2` and initial use count `2`.

This is deliberate isolation. If the retry still fails, these frozen variables become the next candidates rather than being changed simultaneously.

## Implementation

The Android oracle now starts a channel-0 reader before the first startup write, then performs three sequential `PPPP_Write` calls without any blocking `PPPP_Read` in the sending thread:

```text
4881
9029 02 02 01 00
768  00 00 00 00 00 00 00 00
```

The control-reader thread records only sanitized metadata. It does not emit raw authenticated buffers, authInfo, nonce, HMAC, DID, License, InitString, or camera password.

`phase2c3_run.py` locks fresh cloud discovery to `POOL` only. It intentionally repeats `POOL` in both approved target slots so the legacy preflight helper cannot silently fall back to a different camera.

## Offline verification

Run before building or contacting a camera:

```powershell
python -m unittest discover -s tests -v
```

The Phase 2C.3 regression contract checks:

- channel-0 reader startup precedes the first command write;
- command order is `4881 -> 9029 -> 768`;
- there is no `readCommandResponse()` or `PPPP_Read` between those three writes;
- realtime payload construction remains `02 02 01 00` with the Phase 2C.3 defaults;
- command `768` carries an eight-zero-byte payload;
- TNP application version remains `2`.

## Live attempt policy

Maximum one camera connection attempt per evaluation run.

Run a fresh preflight first and confirm the selected camera is `POOL`, online, model `83`, normalized `y291ga`, type `2`.

Do not automatically change connect flags, initialization strategy, TNP version, or native library after a failure. Preserve the sanitized event report and stop for analysis.

## Outcome interpretation

Strong support for the startup-state-machine hypothesis:

- `4882` is received where the earlier oracle received nothing; and/or
- channel 2 or channel 3 begins producing TNP video units; and
- the old `-3012` remote-close boundary is avoided.

If `-3012` still occurs with no valid response, the burst-only hypothesis is weakened and the next investigation should compare DRW/native session behavior, PPPP generation/flags/initializer, and secret HMAC correctness without changing them during this controlled run.
