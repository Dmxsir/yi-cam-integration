from __future__ import annotations

import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yi_cloud_probe as cloud
from yi_account_credentials import YiAccountCredentialStore
from yi_addon_backend import YiAddonBackend
from yi_camera_manager import _stable_id
from yi_camera_runtime import RuntimeDescriptor
from yi_capability_probe_runtime import YiCapabilityProbe
from yi_cloud_session import YiCloudSession, YiMaterialBroker, request_runtime_material
from yi_runtime_lifecycle import RuntimeLifecycleConfig, _CameraRuntimeController, runtime_child_environment
from yi_tnp_oracle import CameraMaterial


CAMERA_A = "e2f22804fecdbd8c3561"
CAMERA_B = "6b1f53303a732ccc8c6a"


class _FakeManager:
    login_count = 0
    refresh_count = 0
    instances: list["_FakeManager"] = []

    def __init__(self, timeout: float = 10.0, *, environment=None) -> None:
        self.timeout = timeout
        self.environment = dict(environment or {})
        self.authenticated = False
        self.closed = False
        self._camera_count = 0
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.login_count = 0
        cls.refresh_count = 0
        cls.instances = []

    @property
    def camera_count(self) -> int:
        return self._camera_count

    def login(self) -> None:
        type(self).login_count += 1
        time.sleep(0.01)
        self.authenticated = True

    def refresh_devices(self) -> None:
        type(self).refresh_count += 1
        self._camera_count = 2

    def discover(self, *, fetch_tnp: bool = False, refresh: bool = False):
        if refresh:
            self.refresh_devices()
        return []

    def _tnp_info(self, stable_id: str):
        return {"DID": f"did-{stable_id}", "InitString": "server", "License": "key:license"}

    def close(self) -> None:
        self.closed = True


class _ExpiringManager(_FakeManager):
    expired_once = False
    operation_count = 0

    @classmethod
    def reset(cls) -> None:
        super().reset()
        cls.expired_once = False
        cls.operation_count = 0

    def discover(self, *, fetch_tnp: bool = False, refresh: bool = False):
        type(self).operation_count += 1
        if not type(self).expired_once:
            type(self).expired_once = True
            raise cloud.YiCloudError("session_expired", "The YI cloud session expired.")
        return super().discover(fetch_tnp=fetch_tnp, refresh=refresh)


class _TransportFailingManager(_FakeManager):
    def discover(self, *, fetch_tnp: bool = False, refresh: bool = False):
        raise cloud.YiCloudError("transport_error", "The HTTPS request failed.")


def _runtime_result(stable_id: str):
    return (
        CameraMaterial(
            name="camera",
            raw_model="6",
            normalized_model="yunyi.camera.y20",
            cloud_uid="uid-secret",
            pppp_did="did-secret",
            server="server-secret",
            device_key="key-secret",
            password="password-secret",
            encrypted=True,
            wakeup=False,
        ),
        RuntimeDescriptor(
            stable_id=stable_id,
            stream_id=f"yi_{stable_id}",
            name="camera",
            raw_model="6",
            normalized_model="yunyi.camera.y20",
            transport="tnp",
            cloud_online_reported=True,
            encrypted=True,
            wakeup=False,
            profile_candidate="tnp_v2_resolution_1_h264_aac",
            profile_source="test",
        ),
    )


class YiCloudSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeManager.reset()
        _ExpiringManager.reset()
        _TransportFailingManager.reset()

    @staticmethod
    def account_payload() -> dict[str, str]:
        return {
            "region": "eu",
            "country": "IL",
            "account": "account-canary",
            "password": "password-canary",
            "device_brand": "samsung",
            "device_model": "SM-S901B",
            "android_version": "13",
            "language": "en-US",
        }

    def test_account_validation_session_is_adopted_by_immediate_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = YiAccountCredentialStore(Path(temporary) / "yi.env")
            session = YiCloudSession()
            backend = YiAddonBackend(cloud_session=session)
            with (
                mock.patch("yi_cloud_session.YiCameraManager", _FakeManager),
                mock.patch.object(store, "_persist"),
                mock.patch.object(store, "_apply"),
            ):
                result = store.configure(self.account_payload(), cloud_session=session)
                backend.discover(fetch_tnp=True, reason="account_replace")

        self.assertEqual(result["camera_count"], 2)
        self.assertEqual(_FakeManager.login_count, 1)
        self.assertEqual(len(_FakeManager.instances), 1)
        self.assertEqual(session.safe_status()["cloud_login_attempt_total"], 1)
        self.assertEqual(session.safe_status()["cloud_session_reuse_total"], 1)

    def test_initial_and_periodic_discovery_use_one_login(self) -> None:
        session = YiCloudSession()
        with mock.patch("yi_cloud_session.YiCameraManager", _FakeManager):
            for reason in ("initial_discovery", "ha_discovery", "ha_discovery"):
                session.discover(fetch_tnp=True, reason=reason)
        status = session.safe_status()
        self.assertEqual(_FakeManager.login_count, 1)
        self.assertEqual(status["cloud_login_success_total"], 1)
        self.assertEqual(status["cloud_session_reuse_total"], 2)

    def test_concurrent_callers_single_flight_first_login(self) -> None:
        session = YiCloudSession()
        barrier = threading.Barrier(9)
        errors: list[Exception] = []

        def discover() -> None:
            barrier.wait()
            try:
                session.discover()
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with mock.patch("yi_cloud_session.YiCameraManager", _FakeManager):
            threads = [threading.Thread(target=discover) for _ in range(8)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

        self.assertEqual(errors, [])
        self.assertEqual(_FakeManager.login_count, 1)

    def test_ensure_session_returns_same_manager_and_generation(self) -> None:
        session = YiCloudSession()
        with mock.patch("yi_cloud_session.YiCameraManager", _FakeManager):
            first, first_generation = session.ensure_session("test")
            second, second_generation = session.ensure_session("test")
        self.assertIs(first, second)
        self.assertEqual(first_generation, second_generation)

    def test_exact_20202_category_relogs_once_and_retries_once(self) -> None:
        session = YiCloudSession()
        with mock.patch("yi_cloud_session.YiCameraManager", _ExpiringManager):
            session.discover()
        status = session.safe_status()
        self.assertEqual(_ExpiringManager.login_count, 2)
        self.assertEqual(_ExpiringManager.operation_count, 2)
        self.assertEqual(status["cloud_relogin_total"], 1)
        self.assertEqual(status["cloud_login_attempt_total"], 2)

    def test_concurrent_20202_callers_share_the_single_relogin(self) -> None:
        session = YiCloudSession()
        barrier = threading.Barrier(7)

        def discover() -> None:
            barrier.wait()
            session.discover()

        with mock.patch("yi_cloud_session.YiCameraManager", _ExpiringManager):
            threads = [threading.Thread(target=discover) for _ in range(6)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()

        self.assertEqual(_ExpiringManager.login_count, 2)
        self.assertEqual(_ExpiringManager.operation_count, 7)
        self.assertEqual(session.safe_status()["cloud_relogin_total"], 1)

    def test_transport_and_server_failures_do_not_relogin(self) -> None:
        session = YiCloudSession()
        with mock.patch("yi_cloud_session.YiCameraManager", _TransportFailingManager):
            for _ in range(2):
                with self.assertRaises(cloud.YiCloudError):
                    session.discover()
        status = session.safe_status()
        self.assertEqual(_TransportFailingManager.login_count, 1)
        self.assertEqual(status["cloud_relogin_total"], 0)

    def test_runtime_generations_and_camera_ids_reuse_the_parent_session(self) -> None:
        session = YiCloudSession()
        with (
            mock.patch("yi_cloud_session.YiCameraManager", _FakeManager),
            mock.patch("yi_cloud_session.runtime_material_from_manager", side_effect=lambda _m, sid: _runtime_result(sid)),
        ):
            for stable_id in (CAMERA_A, CAMERA_B, CAMERA_A, CAMERA_B):
                material, _descriptor = session.runtime_material(stable_id)
                material.clear()
        self.assertEqual(_FakeManager.login_count, 1)
        self.assertEqual(session.safe_status()["cloud_session_reuse_total"], 3)

    def test_runtime_child_command_and_environment_have_no_cloud_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = RuntimeLifecycleConfig(
                python=sys.executable,
                env_file=root / "secret.env",
                runtime_root=root,
                worker_dir=root,
                stable_relay=root / "relay.py",
                supervisor=root / "supervisor.py",
                state_dir=root,
                material_socket=root / "material.sock",
            )
            controller = _CameraRuntimeController(CAMERA_A, config)
            with mock.patch.dict(
                os.environ,
                {
                    "YI_ACCOUNT": "account-canary",
                    "YI_PASSWORD": "password-canary",
                    "YI_ADDON_API_TOKEN": "api-token-canary",
                    "SAFE_CHILD_VALUE": "preserved",
                },
            ):
                child_env = runtime_child_environment()
                command = controller._command()
                probe_command = YiCapabilityProbe._relay_command(SimpleNamespace(config=config), CAMERA_A)

        command_text = " ".join(command)
        self.assertNotIn("--env-file", command)
        self.assertNotIn("secret.env", command_text)
        self.assertIn("--material-socket", command)
        self.assertNotIn("--env-file", probe_command)
        self.assertIn("--material-socket", probe_command)
        self.assertNotIn("YI_ACCOUNT", child_env)
        self.assertNotIn("YI_PASSWORD", child_env)
        self.assertNotIn("YI_ADDON_API_TOKEN", child_env)
        self.assertEqual(child_env["SAFE_CHILD_VALUE"], "preserved")

    def test_safe_status_and_backend_health_never_expose_session_secrets(self) -> None:
        session = YiCloudSession()
        with mock.patch("yi_cloud_session.YiCameraManager", _FakeManager):
            session.ensure_session("test")
        raw = json.dumps(YiAddonBackend(cloud_session=session).health(), sort_keys=True)
        for secret in ("account-canary", "password-canary", "token-canary", "token_secret"):
            self.assertNotIn(secret, raw)
        self.assertIn("cloud_login_attempt_total", raw)

    def test_devices_and_tnp_cache_share_one_session(self) -> None:
        environment = {
            "YI_REGION": "eu",
            "YI_COUNTRY": "IL",
            "YI_ACCOUNT": "account",
            "YI_PASSWORD": "password",
            "YI_DEVICE_BRAND": "samsung",
            "YI_DEVICE_MODEL": "SM-S901B",
            "YI_ANDROID_VERSION": "13",
            "YI_LANGUAGE": "en-US",
        }
        uid = "camera-uid"
        responses = [
            ({"data": {"userid": 1, "token": "token", "token_secret": "secret"}}, {}),
            ({"data": [{"uid": uid}]}, {}),
            ({"data": {"DID": "did", "InitString": "server", "License": "key:license"}}, {}),
        ]
        session = YiCloudSession()
        with (
            mock.patch.dict(os.environ, environment, clear=False),
            mock.patch("yi_camera_manager.cloud.get_json", side_effect=responses) as get_json,
        ):
            session.discover(fetch_tnp=False)
            stable_id = _stable_id(uid)
            first = session.tnp_info(stable_id)
            second = session.tnp_info(stable_id)
        self.assertEqual(first, second)
        self.assertEqual(get_json.call_count, 3)
        self.assertEqual(
            [call.args[1] for call in get_json.call_args_list],
            ["/v4/users/login", "/v4/devices/list", "/v4/tnp/device_info"],
        )
        self.assertEqual(session.safe_status()["cloud_login_attempt_total"], 1)

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "AF_UNIX is required")
    def test_private_broker_round_trip_has_0600_socket_and_no_secret_file(self) -> None:
        session = YiCloudSession()
        with tempfile.TemporaryDirectory() as temporary:
            socket_path = Path(temporary) / "material.sock"
            broker = YiMaterialBroker(socket_path, session)
            with (
                mock.patch("yi_cloud_session.YiCameraManager", _FakeManager),
                mock.patch("yi_cloud_session.runtime_material_from_manager", side_effect=lambda _m, sid: _runtime_result(sid)),
            ):
                broker.start()
                try:
                    material, descriptor = request_runtime_material(socket_path, CAMERA_A)
                    self.assertEqual(stat.S_IMODE(socket_path.stat().st_mode), 0o600)
                finally:
                    broker.close()
            self.assertEqual(descriptor.stable_id, CAMERA_A)
            self.assertEqual(material.password, "password-secret")
            self.assertFalse(socket_path.exists())


class YiSessionExpiryClassificationTests(unittest.TestCase):
    def test_only_exact_signed_endpoint_code_20202_is_session_expired(self) -> None:
        self.assertEqual(cloud._response_failure_category(200, 20202, "", False), "session_expired")
        self.assertEqual(cloud._response_failure_category(500, 50000, "", False), "server_rejection")
        self.assertEqual(cloud._response_failure_category(200, 20202, "", True), "server_rejection")


if __name__ == "__main__":
    unittest.main()
