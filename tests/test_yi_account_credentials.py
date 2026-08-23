from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yi_cloud_probe as cloud
import yi_tnp_oracle as oracle
from yi_account_credentials import ENV_KEYS, YiAccountCredentialError, YiAccountCredentialStore


class YiAccountCredentialStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = {key: os.environ.get(key) for key in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "yi.env"
        self.store = YiAccountCredentialStore(self.path)

    def tearDown(self) -> None:
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        for key, value in self.previous.items():
            if value is not None:
                os.environ[key] = value
        self.tempdir.cleanup()

    @staticmethod
    def payload() -> dict[str, str]:
        return {
            "region": "eu",
            "country": "IL",
            "account": "example@example.com",
            "password": "fake-pass=with#chars",
            "device_brand": "samsung",
            "device_model": "SM-S901B",
            "android_version": "13",
            "language": "en-US",
        }

    def test_configure_validates_then_persists_mode_0600_and_returns_no_secrets(self) -> None:
        responses = [
            ({"code": "20000", "data": {"userid": 123, "token": "fake-token", "token_secret": "fake-secret"}}, {}),
            ({"code": "20000", "data": [{"name": "one"}, {"name": "two"}]}, {}),
        ]
        with mock.patch("yi_account_credentials.cloud.get_json", side_effect=responses):
            result = self.store.configure(self.payload())

        self.assertTrue(result["ok"])
        self.assertTrue(result["configured"])
        self.assertEqual(result["camera_count"], 2)
        self.assertFalse(result["secrets_exposed"])
        self.assertNotIn("account", result)
        self.assertNotIn("password", result)
        self.assertNotIn("token", result)
        self.assertNotIn("token_secret", result)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

        for key in ENV_KEYS:
            os.environ.pop(key, None)
        oracle.load_env_file(self.path)
        self.assertEqual(os.environ["YI_ACCOUNT"], self.payload()["account"])
        self.assertEqual(os.environ["YI_PASSWORD"], self.payload()["password"])

        status = self.store.status()
        self.assertTrue(status["configured"])
        self.assertEqual(status["credential_file_mode"], "0600")
        self.assertNotIn("account", status)
        self.assertNotIn("password", status)

    def test_invalid_credentials_are_not_persisted(self) -> None:
        failure = cloud.YiCloudError("invalid_credentials", "YI rejected the login credentials.")
        with mock.patch("yi_account_credentials.cloud.get_json", side_effect=failure):
            with self.assertRaises(YiAccountCredentialError) as raised:
                self.store.configure(self.payload())
        self.assertEqual(raised.exception.code, "invalid_credentials")
        self.assertFalse(self.path.exists())
        self.assertFalse(self.store.status()["configured"])

    def test_rejects_unknown_fields_and_unsafe_dotenv_values(self) -> None:
        payload = self.payload()
        payload["unexpected"] = "value"
        with self.assertRaises(YiAccountCredentialError):
            self.store.configure(payload)

        payload = self.payload()
        payload["password"] = "line1\nline2"
        with self.assertRaises(YiAccountCredentialError):
            self.store.configure(payload)

        payload = self.payload()
        payload["password"] = '"wrapped"'
        with self.assertRaises(YiAccountCredentialError):
            self.store.configure(payload)


if __name__ == "__main__":
    unittest.main()
