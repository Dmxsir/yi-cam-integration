from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yi_online_status import AvailabilityRecord
from yi_persistent_backend import YiPersistentAddonBackend
from yi_runtime_policy import YiRuntimePolicyStore


CAMERA_A = "e2f22804fecdbd8c3561"
CAMERA_B = "867ecdee5a3692c669f9"


class _FakeLifecycle:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.running: set[str] = set()

    def start(self, stable_id: str):
        self.started.append(stable_id)
        self.running.add(stable_id)
        return {"stable_id": stable_id, "desired_running": True, "process_alive": True}

    def stop(self, stable_id: str):
        self.stopped.append(stable_id)
        self.running.discard(stable_id)
        return {"stable_id": stable_id, "desired_running": False, "process_alive": False}

    def status(self, stable_id: str):
        running = stable_id in self.running
        return {
            "stable_id": stable_id,
            "runtime_state": "running" if running else "stopped",
            "desired_running": running,
            "process_alive": running,
        }


class _FailingCameraManager:
    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    def discover(self, *, fetch_tnp: bool = True):
        raise TimeoutError("simulated cloud outage")

    def close(self) -> None:
        return


class RuntimePolicyStoreTests(unittest.TestCase):
    def test_round_trip_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime-policy.json"
            store = YiRuntimePolicyStore(path)
            self.assertEqual(store.desired_running_ids(), ())

            store.set_desired_running(CAMERA_A, True)
            self.assertEqual(store.desired_running_ids(), (CAMERA_A,))
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o600)

            reloaded = YiRuntimePolicyStore(path)
            self.assertTrue(reloaded.desired_running(CAMERA_A))
            reloaded.set_desired_running(CAMERA_A, False)
            self.assertEqual(reloaded.desired_running_ids(), ())

    def test_reconcile_keeps_undiscovered_camera_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = YiRuntimePolicyStore(Path(temporary) / "runtime-policy.json")
            store.set_desired_running(CAMERA_A, True)
            store.set_desired_running(CAMERA_B, True)
            lifecycle = _FakeLifecycle()
            backend = YiPersistentAddonBackend(runtime_policy=store, lifecycle=lifecycle)

            # Without an availability probe the compatibility behavior remains:
            # discovered desired cameras may start, undiscovered cameras stay pending.
            backend._cameras = {CAMERA_A: object()}  # type: ignore[assignment]
            result = backend._reconcile_runtime_policy()

            self.assertEqual(lifecycle.started, [CAMERA_A])
            self.assertEqual(result["desired_running_count"], 2)
            self.assertEqual(result["restored_count"], 1)
            self.assertEqual(result["pending_count"], 1)
            self.assertEqual(backend._restore_pending, {CAMERA_B})

    def test_reconcile_starts_online_and_keeps_offline_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = YiRuntimePolicyStore(Path(temporary) / "runtime-policy.json")
            store.set_desired_running(CAMERA_A, True)
            store.set_desired_running(CAMERA_B, True)
            lifecycle = _FakeLifecycle()
            backend = YiPersistentAddonBackend(runtime_policy=store, lifecycle=lifecycle)
            backend.availability_probe = object()  # type: ignore[assignment]
            backend._cameras = {CAMERA_A: object(), CAMERA_B: object()}  # type: ignore[assignment]
            backend._availability = {
                CAMERA_A: AvailabilityRecord(state="online", source="pppp_check_dev_online", native_result=1),
                CAMERA_B: AvailabilityRecord(state="offline", source="pppp_check_dev_online", native_result=0),
            }

            result = backend._reconcile_runtime_policy()

            self.assertEqual(lifecycle.started, [CAMERA_A])
            self.assertEqual(lifecycle.stopped, [])
            self.assertEqual(result["restored_count"], 1)
            self.assertEqual(result["offline_pending_count"], 1)
            self.assertEqual(result["pending_count"], 1)
            self.assertEqual(backend._restore_pending, {CAMERA_B})
            self.assertEqual(store.desired_running_ids(), (CAMERA_B, CAMERA_A) if CAMERA_B < CAMERA_A else (CAMERA_A, CAMERA_B))

    def test_offline_refresh_stops_runtime_but_preserves_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = YiRuntimePolicyStore(Path(temporary) / "runtime-policy.json")
            store.set_desired_running(CAMERA_A, True)
            lifecycle = _FakeLifecycle()
            lifecycle.running.add(CAMERA_A)
            backend = YiPersistentAddonBackend(runtime_policy=store, lifecycle=lifecycle)
            backend.availability_probe = object()  # type: ignore[assignment]
            backend._cameras = {CAMERA_A: object()}  # type: ignore[assignment]
            backend._availability = {
                CAMERA_A: AvailabilityRecord(state="offline", source="pppp_check_dev_online", native_result=0),
            }

            result = backend._reconcile_runtime_policy()

            self.assertEqual(lifecycle.stopped, [CAMERA_A])
            self.assertEqual(result["offline_pending_count"], 1)
            self.assertEqual(backend._restore_pending, {CAMERA_A})
            self.assertTrue(store.desired_running(CAMERA_A))

    def test_cloud_discovery_failure_does_not_clear_pending_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = YiRuntimePolicyStore(Path(temporary) / "runtime-policy.json")
            store.set_desired_running(CAMERA_A, True)
            backend = YiPersistentAddonBackend(runtime_policy=store, lifecycle=_FakeLifecycle())

            with patch("yi_persistent_backend.YiCameraManager", _FailingCameraManager):
                with self.assertRaises(TimeoutError):
                    backend.discover(fetch_tnp=True)

            self.assertEqual(store.desired_running_ids(), (CAMERA_A,))
            self.assertEqual(backend._restore_pending, {CAMERA_A})
            self.assertEqual(backend._last_error["category"], "transport_error")


if __name__ == "__main__":
    unittest.main()
