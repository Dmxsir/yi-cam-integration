# Checkpoint — 2026-08-23 — Phase 6C.6 availability + persistence

## Status

- Phase 6C.5: COMPLETE.
- Phase 6C.6: COMPLETE.
- Phase 6C: COMPLETE.
- Phase 6D: ACTIVE.

This checkpoint records the authoritative YI online/offline source, the availability-aware persistence implementation, and the final live Phase 6C.6 exit-gate proof.

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

## Implemented availability/runtime policy

### `yi_online_status.py`

Reusable secret-safe online-status layer:

- wraps the proven AArch64/Bionic `PPPP_CheckDevOnline` worker;
- keeps DID/InitString only in process memory;
- does not persist or return transport secrets;
- exposes `online`, `offline` or `unknown` plus `last_online_at`;
- caches transient material after discovery so periodic refresh does not require repeated cloud login;
- refresh is shutdown-aware and stops between camera probes.

The development smoke prepares the worker/library under:

```text
<runtime-root>/data/local/tmp/yi-online-status/
```

The Home Assistant App packaging path now stages this proven worker and an export-capable YI `libPPPP_API.so` into the generated App build context; no compiler is required at App runtime.

### `yi_persistent_backend.py`

API camera/status records add:

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

## Final live Phase 6C.6 exit gate

Live run on 2026-08-23 passed end-to-end using isolated backend/go2rtc ports and a temporary persistent data directory.

Observed markers:

```text
python_compile=PASS
runtime_policy_unit_tests=PASS
production_modified=false
production_go2rtc_ports_untouched=1984,8554
persistent_data_dir_isolated=PASS
online_count=4
offline_count=3
unknown_count=0
cloud_hint_disagreement_count=3
availability_preflight=PASS
service_launch_1=PASS
backend_availability_inventory=PASS
persistent_start_http=PASS
offline_start_deferred_without_runtime=PASS
first_launch_dual_rtsp=PASS
capability_cache_under_data=PASS
reprobe_preserved_runtime_intent=PASS
offline_pending_intent_persisted=PASS
service_shutdown_1=PASS
service_launch_2=PASS
dual_runtime_restore_after_restart=PASS
offline_runtime_remained_pending_after_restart=PASS
dual_rtsp_after_backend_restart=PASS
offline_pending_intent_clear=PASS
explicit_stop_persisted=PASS
service_shutdown_2=PASS
service_launch_3=PASS
selective_runtime_restore=PASS
stopped_camera_remained_stopped=PASS
runtime_policy_final_cleanup=PASS
service_shutdown_3=PASS
persistent_service_shutdown_cleanup=PASS
PHASE6C_PERSISTENCE_SMOKE=PASS
```

Concrete cameras used by the smoke:

- primary online camera: PTZ `e2f22804fecdbd8c3561`;
- peer online camera: pool `867ecdee5a3692c669f9`;
- offline/pending camera: zforce 800 `8e97091cc281fe207f8c`.

What the run proves:

1. The authoritative 4-online/3-offline inventory is available inside the backend.
2. PTZ + pool can be explicitly started and both serve H264 + AAC RTSP.
3. Starting the offline zforce camera persists desired intent but creates no runtime process.
4. Capability cache is stored under the persistent data root and reprobe does not alter desired-running intent.
5. A full backend/App-style shutdown and restart restores both online desired cameras automatically.
6. The offline desired camera remains pending/stopped after restart.
7. Clearing the offline intent and explicitly stopping pool persist correctly.
8. A third launch restores only PTZ while pool remains stopped.
9. Runtime policy cleanup, service shutdown and managed publisher cleanup all pass.
10. Production go2rtc configuration/ports remain untouched.

## Exit decision

`PHASE6C_PERSISTENCE_SMOKE=PASS` closes Phase 6C.6 and therefore closes Phase 6C completely.

## Phase 6D handoff

Phase 6D Home Assistant App packaging is now active. Initial scaffold added after this proof:

- root `repository.yaml`;
- `yi_home/config.yaml` with amd64-only experimental App metadata and RTSP port 8554;
- explicit Home Assistant base Dockerfile with Python, FFmpeg, QEMU user-mode and pinned go2rtc 1.9.14 download/checksum;
- `/run.sh` generating a mode-0600 internal backend token and publishing Supervisor discovery service `yi_home`;
- protected-mode AppArmor profile with no host network/full-access/Docker API requirement;
- `tools/prepare_ha_app_context.py` to stage the proven project/native runtime into the App Docker context without copying `.env.local` or credentials;
- `tools/phase3_pppp_probe/run_phase6d_app_context_smoke.sh` for static/staging validation and optional Docker build.

Next gate: run the Phase 6D App-context smoke, then perform the first actual amd64 container build and HA OS Local App start.
