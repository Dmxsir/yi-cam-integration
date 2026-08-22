from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yi_persistent_backend import YiPersistentAddonBackend
from yi_runtime_policy import YiRuntimePolicyStore


CAMERA_A = "e2f22804fecdbd8c3561"
CAMERA_B = "867ecdee5a3692c669f9"


class _FakeLifecycle:
    def __init__(self) -> None:
        self.started: list[str] = []

    def start(self, stable_id: str):
        self.started.append(stable_id)
        return {"stable_id": stable_id, "desired_running": True}


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

    def test_reconcile_keeps_unavailable_camera_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = YiRuntimePolicyStore(Path(temporary) / "runtime-policy.json")
            store.set_desired_running(CAMERA_A, True)
            store.set_desired_running(CAMERA_B, True)
            lifecycle = _FakeLifecycle()
            backend = YiPersistentAddonBackend(runtime_policy=store, lifecycle=lifecycle)

            # Reconciliation needs only the discovered stable-id keys. CameraState
            # contents are intentionally irrelevant to runtime policy matching.
            backend._cameras = {CAMERA_A: object()}  # type: ignore[assignment]
            result = backend._reconcile_runtime_policy()

            self.assertEqual(lifecycle.started, [CAMERA_A])
            self.assertEqual(result["desired_running_count"], 2)
            self.assertEqual(result["restored_count"], 1)
            self.assertEqual(result["pending_count"], 1)
            self.assertEqual(backend._restore_pending, {CAMERA_B})

    def test_cloud_discovery_failure_does_not_clear_pending_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = YiRuntimePolicyStore(Path(temporary) / "runtime-policy.json")
            store.set_desired_running(CAMERA_A, True)
            backend = YiPersistentAddonBackend(runtime_policy=store, lifecycle=_FakeLifecycle())

            with patch("yi_addon_backend.YiCameraManager", _FailingCameraManager):
                with self.assertRaises(TimeoutError):
                    backend.discover(fetch_tnp=True)

            self.assertEqual(store.desired_running_ids(), (CAMERA_A,))
            self.assertEqual(backend._restore_pending, {CAMERA_A})
            self.assertEqual(backend._last_error["category"], "transport_error")


if __name__ == "__main__":
    unittest.main()
