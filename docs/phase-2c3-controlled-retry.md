# Phase 2C.3 — controlled startup-burst retry

## Purpose

Phase 2C.2 produced a strict runtime A/B comparison between two successful official YI Home captures and the failed Android oracle. The highest-value difference that can be isolated without changing native transport inputs is the application startup state machine.

Successful older official runtime sequence against `POOL` / model 83 / `y291ga`:

1. `4881` — 56-byte TNP control unit.
2. `9029` — payload `02 02 01 00`.
3. `768` — `IOTYPE_USER_IPCAM_AUDIOSTART`, eight zero payload bytes.
4. Only then does the client process the first channel-0 response.

The failed oracle instead sent `4881` and immediately blocked waiting for a response. All visible `4881` structural fields matched the successful official message. Both official captures and the oracle use TNP application version 2.

## Isolated change

The Android oracle on branch `phase-2c3-startup-burst` now sends:

`4881 -> 9029 -> 768 -> first blocking channel-0 read`

No deliberate changes are made to:

- native PPPP library generation;
- `PPPP_Initialize(new byte[] {0}, 12)`;
- connection flag `0x4B`;
- TNP application version 2;
- HMAC-SHA1 authentication construction;
- session nonce lifetime;
- command nonce generation;
- camera resolution (`2`);
- start use count (`2`).

Each command still uses a separate `PPPP_Write` call and builds a separately authenticated IOCTRL using the stable seven-character session nonce plus a fresh eight-character command nonce.

The important refinement is that **no host-side `event()`/flush occurs between the three writes**. Capture B carried all three TNP units in one DRW sequence-0 packet. We do not claim that the official app made one native write; instead, three back-to-back writes are preserved while diagnostic I/O is moved until after the burst so the unchanged PPPP library can coalesce or schedule them naturally.

The aggregate `startup_burst` event records only secret-safe structure:

- command numbers and payload lengths;
- `blockingReadBetweenCommands=false`;
- `diagnosticFlushBetweenCommands=false`;
- `ppppWriteCount=3`;
- burst elapsed time in microseconds.

## Target restriction

Use `phase2c3_retry.py`, not the historical generic runner. The default target is `POOL`. `מחסן` is also allowed because it is the same verified model-83 / `y291ga` / TNP family, but it must be selected explicitly:

```powershell
python .\phase2c3_retry.py preflight --target "מחסן"
```

There is **no automatic fallback** between cameras. For the chosen target the wrapper requires:

- exact requested camera name;
- raw model `83`;
- normalized model `y291ga`;
- cloud type 2;
- current online status.

If the requested camera is offline or its identity does not match, the run stops before the Android oracle is launched.

## Scope

The runner deliberately does not call the later elementary-stream reconstruction path. The experiment stops after one Android oracle session and summarizes only secret-safe evidence:

- PPPP connection result and mode;
- startup burst completion/timing;
- first parsed channel-0 response and latency;
- whether response `4882` was received;
- channel 2 and channel 3 unit counts;
- whether `-3012` reappeared;
- outcome classification.

No automatic reconnect is implemented.

## Local verification before a live run

From the repository root, run the Python suite first:

```powershell
python -m unittest discover -s tests -v
python -m py_compile yi_cloud_probe.py yi_tnp_oracle.py phase2c3_retry.py tools\yi_pppp_pcap.py
```

The Phase 2C.3 regression test also inspects the Android source to verify that the order is `4881 -> 9029 -> 768 -> readCommandResponse()` and that all three burst writes suppress per-write diagnostic events.

Then rebuild the Android oracle using the same SDK/JDK inputs previously used for Phase 2C:

```powershell
.\oracle\android\build-oracle.ps1 -SdkRoot "<ANDROID_SDK_ROOT>" -JavaHome "<JDK_HOME>"
```

Do not run against a camera if either Python verification or the Android build fails.

## Preflight

For the preferred `POOL` target:

```powershell
python .\phase2c3_retry.py preflight
```

For `מחסן` explicitly:

```powershell
python .\phase2c3_retry.py preflight --target "מחסן"
```

Expected fields include the requested camera name, raw model `83`, normalized model `y291ga`, `p2p_type: 2`, and `cloud_online: true`.

## One controlled attempt

After preflight and build verification, execute exactly one run. Preferred `POOL` example:

```powershell
python .\phase2c3_retry.py run --adb "C:\path\to\adb.exe" --capture-seconds 5
```

Explicit `מחסן` example:

```powershell
python .\phase2c3_retry.py run --target "מחסן" --adb "C:\path\to\adb.exe" --capture-seconds 5
```

Do not repeat automatically if it fails. Preserve the generated ignored `captures/oracle-*` report for analysis.

## Outcome meanings

- `FULL_SUCCESS`: valid `4882` plus both channel 2 and channel 3 traffic.
- `CONTROL_SUCCESS`: valid `4882`, but both expected video channels were not yet observed.
- `PARTIAL_SUCCESS`: the old failure boundary changed without enough evidence for control success.
- `SAME_FAILURE`: `-3012` recurred after the corrected startup burst.
- `DIFFERENT_FAILURE`: a different concrete failure occurred.

A successful result supports the startup state-machine hypothesis. `SAME_FAILURE` substantially weakens it and shifts the next investigation toward native/DRW session behavior while keeping other hypotheses separate.

## Secret handling

The existing secret-safety rules remain unchanged. Do not commit `.env.local`, PCAPs, raw capture directories, APKs, camera credentials, DID, InitString, License, authInfo, nonce contents, or HMAC values.
