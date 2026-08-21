# Phase 2C.3 — controlled startup-burst retry

## Purpose

Phase 2C.2 produced a strict runtime A/B comparison between two successful official YI Home captures and the failed Android oracle. The highest-value difference that can be isolated without changing native transport inputs is the application startup state machine.

Successful older official runtime sequence against `POOL` / model 83 / `y291ga`:

1. `4881` — 56-byte TNP control unit.
2. `9029` — payload `02 02 01 00`.
3. `768` — eight zero payload bytes.
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

The third command uses an eight-byte zero payload. Each call still builds a separately authenticated IOCTRL using the existing stable seven-character session nonce and a fresh eight-character command nonce.

## Target restriction

Use `phase2c3_retry.py`, not the historical generic runner, for this experiment. The wrapper forces the existing cloud preflight to select `POOL` only and verifies:

- camera name `POOL`;
- raw model `83`;
- normalized model `y291ga`;
- cloud type 2;
- current online status.

If that identity is not available, the run stops before the Android oracle is launched.

## Scope

The runner deliberately does not call the later elementary-stream reconstruction path. The experiment stops after one Android oracle session and summarizes only secret-safe evidence:

- PPPP connection result and mode;
- startup burst completion;
- first parsed channel-0 response;
- whether response `4882` was received;
- channel 2 and channel 3 unit counts;
- whether `-3012` reappeared;
- outcome classification.

No automatic reconnect or fallback target is implemented.

## Local verification before a live run

From the repository root, run the existing Python suite first:

```powershell
python -m unittest discover -s tests -v
python -m py_compile yi_cloud_probe.py yi_tnp_oracle.py phase2c3_retry.py tools\yi_pppp_pcap.py
```

Then rebuild the Android oracle using the same SDK/JDK inputs previously used for Phase 2C:

```powershell
.\oracle\android\build-oracle.ps1 -SdkRoot "<ANDROID_SDK_ROOT>" -JavaHome "<JDK_HOME>"
```

Do not run against a camera if either Python verification or the Android build fails.

## Preflight

Run cloud-only target validation first:

```powershell
python .\phase2c3_retry.py preflight
```

Expected identity fields include `POOL`, raw model `83`, normalized model `y291ga`, and `cloud_online: true`.

## One controlled attempt

After preflight and build verification, execute exactly one run with the authorized ADB binary path:

```powershell
python .\phase2c3_retry.py run --adb "C:\path\to\adb.exe" --capture-seconds 5
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
