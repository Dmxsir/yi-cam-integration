# Checkpoint — 2026-08-23 — Phase 6C.6 availability + persistence

## Status

- Phase 6C.5: COMPLETE.
- Phase 6C.6: ACTIVE.
- This checkpoint records the authoritative YI online/offline source and the availability-aware persistence implementation before the final live persistence exit-gate run.

## Live availability proof

The YI cloud `/v4/devices/list` payload is not a live availability source for this account. All seven cameras returned:

- `online=true`
- `state=1`

while the official YI Home UI visibly showed four online cameras and three offline cameras.

A secret-safe parity probe using the YI native `PPPP_CheckDevOnline(p2pid, server, 2, &lastOnlineTime)` path returned an exact UI match:

### Online

- `צד בית` — `6a046d860b2d71ea7d7c`
- `מחסן` — `51aad28e24ea012f70fa`
- `ptz` — `e2f22804fecdbd8c3561`
- `pool` — `867ecdee5a3692c669f9`

### Offline

- `zforce 800` — `8e97091cc281fe207f8c` — last online `2026-08-20T15:45:30Z`
- `Living room` — `ca9f37f113913e0875b7` — last online `2025-09-11T17:53:55Z`
- `patio` — `7b6617446111f6f808c7` — last online `2025-11-20T07:24:12Z`

Live markers:

```text
camera_count=7
tnp_camera_count=7
resolved_tnp_count=7
online_count=4
offline_count=3
unknown_count=0
cloud_hint_disagreement_count=3
all_tnp_online_checks_resolved=PASS
secret_safe_status_output=PASS
PHASE6_ONLINE_STATUS_PROBE=PASS
```

Conclusion:

- `PPPP_CheckDevOnline` is the authoritative TNP availability source.
- `cloud_online_reported` / `/v4/devices/list.online` is retained only as a diagnostic cloud hint and must not drive runtime restore or UI availability.
- Availability, transport material readiness and actual media-runtime state are separate concepts.

## Implementation after proof

### `yi_online_status.py`

Reusable secret-safe online-status layer:

- wraps the proven AArch64/Bionic `PPPP_CheckDevOnline` worker;
- keeps DID/InitString only in process memory;
- does not persist or return transport secrets;
- exposes `online`, `offline` or `unknown` plus `last_online_at`;
- caches transient material after discovery so periodic refresh does not require repeated cloud login;
- refresh is shutdown-aware and stops between camera probes.

The existing development smoke prepares the worker/library under:

```text
<runtime-root>/data/local/tmp/yi-online-status/
```

The future Home Assistant App image must package this worker and an export-capable YI `libPPPP_API.so` directly; no compiler is required at runtime.

### `yi_persistent_backend.py`

Availability is integrated only into the Phase 6C.6 persistent adapter so the proven 6C.1–6C.5 media backend remains unchanged.

API camera/status records now add:

```text
availability_state
availability_source
last_online_at
availability_error
```

Health/inventory expose aggregate online/offline/unknown counts.

Runtime policy semantics:

- persisted `desired_running=true` + `online` => start/restore runtime;
- persisted `desired_running=true` + `offline` => keep intent pending and do not create a PPPP/media runtime;
- if a desired running camera later becomes explicitly offline, stop its runtime but preserve persisted intent;
- `unknown` never tears down an already healthy runtime and is not promoted to online;
- explicit start/restart on an offline camera returns HTTP `202 Accepted`, persists intent and reports `pending_reason=camera_offline`;
- when availability later returns online, periodic reconcile can restore the pending runtime;
- explicit stop clears the persisted intent.

Availability refresh defaults to 30 seconds in the persistent backend and uses cached transient TNP material. Shutdown cancels refresh before lifecycle/publisher teardown so a late reconcile cannot recreate a runtime during service shutdown.

### Regression coverage

`tests/test_yi_runtime_policy.py` now covers:

- policy round trip and mode 0600;
- undiscovered desired camera remains pending;
- availability-aware restore starts online desired cameras only;
- offline desired camera remains pending;
- an already-running camera becoming offline is stopped while persisted intent remains true;
- cloud discovery failure preserves pending intent.

### Live Phase 6C.6 smoke

`tools/phase3_pppp_probe/run_phase6c_persistence_smoke.sh` now:

1. runs the secret-safe online-status preflight and prepares the exact worker/library;
2. requires backend availability to resolve every TNP camera with zero unknowns;
3. selects PTZ + pool only from `availability_state=online`;
4. selects an offline camera (prefers `zforce 800`);
5. starts PTZ + pool and validates dual H264 + AAC RTSP;
6. sends start to the offline camera and requires HTTP 202 with no runtime process;
7. persists all three intents;
8. restarts the backend with the same data directory;
9. requires PTZ + pool to restore automatically while the offline camera remains pending/stopped;
10. clears the offline pending intent, explicitly stops pool, restarts again and requires only PTZ to restore;
11. verifies mode-0600 secret-safe policy/capability files and complete cleanup.

Production go2rtc ports `1984/8554` remain untouched; the persistence smoke uses isolated ports `18104/11986/18556`.

## Current branch changes after the availability proof

Base proof commit: `cf8669b841921881f66d13cfc8f641eb56699b93`.

Files changed after that proof:

- `yi_online_status.py`
- `yi_persistent_backend.py`
- `tests/test_yi_runtime_policy.py`
- `tools/phase3_pppp_probe/run_phase6c_persistence_smoke.sh`

## Next live command

```bash
cd ~/Documents/yi-cam-integration-phase3 && git pull --ff-only && PYTHON=~/Documents/yi-cam-integration/.venv/bin/python bash tools/phase3_pppp_probe/run_phase6c_persistence_smoke.sh
```

Expected key markers include:

```text
python_compile=PASS
runtime_policy_unit_tests=PASS
availability_preflight=PASS
backend_availability_inventory=PASS
offline_start_deferred_without_runtime=PASS
first_launch_dual_rtsp=PASS
reprobe_preserved_runtime_intent=PASS
offline_pending_intent_persisted=PASS
dual_runtime_restore_after_restart=PASS
offline_runtime_remained_pending_after_restart=PASS
dual_rtsp_after_backend_restart=PASS
offline_pending_intent_clear=PASS
explicit_stop_persisted=PASS
selective_runtime_restore=PASS
runtime_policy_final_cleanup=PASS
persistent_service_shutdown_cleanup=PASS
PHASE6C_PERSISTENCE_SMOKE=PASS
```

## Exit decision

Do not mark Phase 6C.6 or Phase 6C COMPLETE until the updated live persistence smoke returns `PHASE6C_PERSISTENCE_SMOKE=PASS`.

After PASS:

1. update `ROADMAP.md` and `docs/development-plan.md` with the authoritative availability proof and 6C.6 live evidence;
2. mark Phase 6C COMPLETE;
3. proceed to Phase 6D Home Assistant App packaging, including the prebuilt online-status worker and export-capable PPPP library in the App image.
