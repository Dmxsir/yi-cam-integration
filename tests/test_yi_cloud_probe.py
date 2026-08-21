import contextlib
import gzip
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import yi_cloud_probe as probe


LOGIN_TOKEN = "LOGIN_TOKEN_MUST_NOT_APPEAR"
TOKEN_SECRET = "TOKEN_SECRET_MUST_NOT_APPEAR"
CAMERA_PASSWORD = "CAMERA_PASSWORD_MUST_NOT_APPEAR"
ENCRYPTED_PASSWORD = ""
UID = "ABCDEFGHIJKLMNOPQRST"


def encrypt_camera_password(uid, plaintext):
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    encryptor = Cipher(algorithms.AES(uid[:16].encode("utf-8")), modes.ECB()).encryptor()
    return (encryptor.update(padded) + encryptor.finalize()).hex()


ENCRYPTED_PASSWORD = encrypt_camera_password(UID, CAMERA_PASSWORD)


def login_response():
    return {
        "code": 20000,
        "data": {"userid": "42", "token": LOGIN_TOKEN, "token_secret": TOKEN_SECRET},
    }


def production_login_response(code="20000", userid=12345678):
    return {
        "code": code,
        "data": {
            "account": "fake-account",
            "birthday": "",
            "email": "fake@example.invalid",
            "first_name": "Fake",
            "flag": False,
            "img": "",
            "last_name": "User",
            "mobile": "",
            "name": "Fake User",
            "openId": "fake-open-id",
            "register_time": "1700000000",
            "token": LOGIN_TOKEN,
            "token_secret": TOKEN_SECRET,
            "userMobileRegion": "IL",
            "user_mobile": "",
            "userid": userid,
        },
    }


def camera_response():
    return {
        "code": 20000,
        "data": [
            {
                "uid": UID,
                "did": "DID-MUST-BE-REDACTED",
                "name": "Living room",
                "model": "6",
                "type": 0,
                "online": True,
                "state": 1,
                "share": False,
                "hasPincode": False,
                "password": ENCRYPTED_PASSWORD,
                "ipcParam": json.dumps(
                    {
                        "ip": "192.168.1.20",
                        "mac": "00:11:22:33:44:55",
                        "rssi": -48,
                        "p2p_encrypt": True,
                        "wakeup": False,
                    }
                ),
            }
        ],
    }


def diagnostic(path):
    return {
        "endpoint": path,
        "gateway": probe.GATEWAY_HOSTS["eu"],
        "http_status": 200,
        "yi_code": 20000,
        "ok": True,
    }


def cli_args(command="discover", *extra):
    return probe.parser().parse_args(
        [
            command,
            "--region",
            "eu",
            "--country",
            "IL",
            "--account",
            "person@example.com",
            "--device-brand",
            "samsung",
            "--device-model",
            "SM-S901B",
            "--android-version",
            "13",
            "--language",
            "en-US",
            *extra,
        ]
    )


def successful_get_json(host, path, params, headers, timeout, **kwargs):
    if path == "/v4/users/login":
        return login_response(), diagnostic(path)
    if path == "/v4/devices/list":
        return camera_response(), diagnostic(path)
    raise AssertionError(f"unexpected endpoint: {path}")


class FakeResponse:
    def __init__(self, status, payload, headers=None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.payload


class YiCloudProbeTests(unittest.TestCase):
    def test_model_resolution_comes_from_apk_feature_assets(self):
        expected = {
            "5": "h20",
            "40": "y30ga",
            "51": "y21ga",
            "83": "y291ga",
            "6": "yunyi.camera.y20",
        }
        self.assertEqual({raw: probe.normalize_model(raw) for raw in expected}, expected)
        self.assertEqual(probe.normalize_model("89"), "UNKNOWN")

    def test_password_transform_matches_independent_vector(self):
        self.assertEqual(
            probe.password_transform("Password123!"),
            "wfpeI0/h40wfilyDLgiH30P2H9IfINyFn83Nr9Mmd6o=",
        )

    def test_device_list_signature_preserves_apk_canonical_order(self):
        self.assertEqual(
            probe.sign_params([("seq", "1"), ("userid", "42")], "tok", "sec"),
            "fc9LWD8hou+WGZCz5JboUWUppTA=",
        )

    def test_tnp_device_info_signature_preserves_apk_canonical_order(self):
        params = probe.tnp_device_info_params("42", "TNP-UID", "tok", "sec")
        self.assertEqual([key for key, _ in params], ["seq", "userid", "uid", "hmac"])
        self.assertEqual(params[-1][1], probe.sign_params(params[:3], "tok", "sec"))

    def test_international_login_uses_account(self):
        params = dict(probe.login_params("eu", "person@example.com", "pw", "brand", "model", "12"))
        self.assertEqual(params["account"], "person@example.com")
        self.assertNotIn("email", params)

    def test_china_login_selects_email_or_mobile(self):
        email = dict(probe.login_params("cn", "person@example.com", "pw", "brand", "model", "12"))
        mobile = dict(probe.login_params("cn", "13800138000", "pw", "brand", "model", "12"))
        self.assertIn("email", email)
        self.assertIn("mobile", mobile)

    def test_default_redaction_covers_cloud_secrets(self):
        value = {"token": "t", "token_secret": "s", "data": [{"password": "cipher", "uid": "u"}]}
        self.assertEqual(
            probe.redact(value),
            {"token": "<redacted>", "token_secret": "<redacted>", "data": [{"password": "<redacted>", "uid": "u"}]},
        )

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "RAW_PASSWORD_MUST_NOT_APPEAR"))
    @mock.patch.object(probe, "get_json", side_effect=successful_get_json)
    def test_discover_logs_in_and_lists_in_one_process(self, get_json_mock, _credentials_mock):
        report = probe.run(cli_args())

        self.assertTrue(report["ok"])
        self.assertEqual([call.args[1] for call in get_json_mock.call_args_list], ["/v4/users/login", "/v4/devices/list"])
        self.assertEqual(report["camera_count"], 1)
        camera = report["cameras"][0]
        self.assertEqual(camera["index"], 1)
        self.assertEqual(camera["uid"], "<redacted>")
        self.assertEqual(camera["did"], "<redacted>")
        self.assertEqual(camera["raw_cloud_model"], "6")
        self.assertEqual(camera["normalized_model"], "yunyi.camera.y20")
        self.assertEqual(camera["p2p_interpretation"], "TUTK/Kalay")
        self.assertEqual(camera["ipcParam"]["mac"], "<redacted>")
        self.assertTrue(camera["encrypted_camera_password_recovery_succeeded"])
        self.assertTrue(camera["p2p_descriptor_has_usable_password"])

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "pw"))
    @mock.patch.object(probe, "get_json", side_effect=successful_get_json)
    def test_cameras_is_a_sanitized_discover_alias(self, get_json_mock, _credentials_mock):
        report = probe.run(cli_args("cameras"))

        self.assertEqual(report["command"], "discover")
        self.assertEqual([call.args[1] for call in get_json_mock.call_args_list], ["/v4/users/login", "/v4/devices/list"])
        self.assertEqual(report["cameras"][0]["uid"], "<redacted>")

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "RAW_PASSWORD_MUST_NOT_APPEAR"))
    @mock.patch.object(probe, "get_json")
    def test_tnp_info_flow_reports_presence_without_session_secrets(self, get_json_mock, _credentials_mock):
        tnp_did = "TNP_DID_MUST_NOT_APPEAR"
        server = "TNP_SERVER_MUST_NOT_APPEAR"
        license_value = "TNP_DEVICE_KEY_MUST_NOT_APPEAR:TNP_LICENSE_TAIL_MUST_NOT_APPEAR"

        def responses(host, path, params, headers, timeout, **kwargs):
            if path == "/v4/users/login":
                return login_response(), diagnostic(path)
            if path == "/v4/devices/list":
                response = camera_response()
                response["data"][0]["type"] = 2
                response["data"][0]["model"] = "51"
                return response, diagnostic(path)
            if path == "/v4/tnp/device_info":
                return {
                    "code": "20000",
                    "data": {"DID": tnp_did, "InitString": server, "License": license_value},
                }, diagnostic(path)
            raise AssertionError(path)

        get_json_mock.side_effect = responses
        report = probe.run(cli_args("tnp-info", "--camera-index", "1", "--show-uid"))
        rendered = json.dumps(report)

        self.assertTrue(report["ok"])
        self.assertEqual(
            [call.args[1] for call in get_json_mock.call_args_list],
            ["/v4/users/login", "/v4/devices/list", "/v4/tnp/device_info"],
        )
        summary = report["tnp_info"]
        self.assertEqual(summary["normalized_model"], "y21ga")
        self.assertTrue(summary["tnp_did_available"])
        self.assertTrue(summary["tnp_server_string_available"])
        self.assertTrue(summary["tnp_license_available"])
        self.assertTrue(summary["tnp_license_device_key_available"])
        self.assertEqual(summary["tnp_license_component_count"], 2)
        for secret in (tnp_did, server, license_value, "TNP_DEVICE_KEY_MUST_NOT_APPEAR", "TNP_LICENSE_TAIL_MUST_NOT_APPEAR"):
            self.assertNotIn(secret, rendered)

    def test_apk_fallback_is_usable_without_claiming_encrypted_recovery(self):
        camera = camera_response()["data"][0]
        camera["password"] = ""
        summary = probe.camera_summary(camera, 1, False)

        self.assertFalse(summary["encrypted_camera_password_recovery_succeeded"])
        self.assertEqual(summary["camera_password_recovery_status"], "not_required_apk_fallback")
        self.assertTrue(summary["p2p_descriptor_has_usable_password"])

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "RAW_PASSWORD_MUST_NOT_APPEAR"))
    @mock.patch.object(probe, "get_json", side_effect=successful_get_json)
    def test_stdout_contains_no_account_or_camera_secrets(self, _get_json_mock, _credentials_mock):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = probe.main(
                [
                    "discover",
                    "--region",
                    "eu",
                    "--country",
                    "IL",
                    "--account",
                    "person@example.com",
                    "--device-brand",
                    "samsung",
                    "--device-model",
                    "SM-S901B",
                    "--android-version",
                    "13",
                    "--language",
                    "en-US",
                ]
            )

        output = stdout.getvalue()
        self.assertEqual(code, 0)
        for secret in (
            "RAW_PASSWORD_MUST_NOT_APPEAR",
            LOGIN_TOKEN,
            TOKEN_SECRET,
            CAMERA_PASSWORD,
            ENCRYPTED_PASSWORD,
            UID,
            "DID-MUST-BE-REDACTED",
            "00:11:22:33:44:55",
        ):
            self.assertNotIn(secret, output)

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "pw"))
    @mock.patch.object(probe, "get_json", side_effect=successful_get_json)
    def test_show_uid_only_reveals_uid(self, _get_json_mock, _credentials_mock):
        report = probe.run(cli_args("discover", "--show-uid"))
        camera = report["cameras"][0]
        self.assertEqual(camera["uid"], UID)
        self.assertEqual(camera["did"], "<redacted>")
        self.assertEqual(camera["ipcParam"]["mac"], "<redacted>")

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "pw"))
    @mock.patch.object(probe, "get_json", side_effect=successful_get_json)
    def test_eu_il_routing_and_headers(self, get_json_mock, _credentials_mock):
        report = probe.run(cli_args())
        first_call = get_json_mock.call_args_list[0]

        self.assertEqual(first_call.args[0], "https://gw-eu.xiaoyi.com")
        self.assertEqual(first_call.args[3]["x-xiaoyi-appCountryCode"], "IL")
        self.assertEqual(report["region"], "EU")
        self.assertEqual(report["country"], "IL")
        self.assertEqual(report["selected_regional_gateway"], "https://gw-eu.xiaoyi.com")

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "pw"))
    @mock.patch.object(probe, "get_json")
    def test_malformed_login_schema_is_classified(self, get_json_mock, _credentials_mock):
        get_json_mock.return_value = ({"code": 20000, "data": []}, diagnostic("/v4/users/login"))
        report = probe.run(cli_args())

        self.assertFalse(report["ok"])
        self.assertEqual(report["error"]["category"], "unexpected_response_schema")
        self.assertFalse(report["requests"][0]["ok"])
        self.assertEqual(report["requests"][0]["http_status"], 200)
        self.assertEqual(report["requests"][0]["yi_code"], 20000)

    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_non_200_http_response_is_sanitized(self, urlopen_mock):
        body = io.BytesIO(json.dumps({"code": 40001, "msg": "invalid password RAW_PASSWORD_MUST_NOT_APPEAR"}).encode())
        urlopen_mock.side_effect = urllib.error.HTTPError(
            "https://gw-eu.xiaoyi.com/v4/users/login?password=RAW_PASSWORD_MUST_NOT_APPEAR",
            401,
            "unauthorized",
            {},
            body,
        )

        with self.assertRaises(probe.YiCloudError) as caught:
            probe.get_json("https://gw-eu.xiaoyi.com", "/v4/users/login", [("password", "RAW_PASSWORD_MUST_NOT_APPEAR")], {}, 1, auth_request=True)

        error = caught.exception
        self.assertEqual(error.category, "invalid_credentials")
        self.assertEqual(error.diagnostic["http_status"], 401)
        self.assertEqual(error.diagnostic["yi_code"], 40001)
        self.assertNotIn("RAW_PASSWORD_MUST_NOT_APPEAR", str(error))
        self.assertNotIn("?", json.dumps(error.diagnostic))

    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_malformed_json_response_is_classified(self, urlopen_mock):
        urlopen_mock.return_value = FakeResponse(200, b"not json")

        with self.assertRaises(probe.YiCloudError) as caught:
            probe.get_json("https://gw-eu.xiaoyi.com", "/v4/users/login", [], {}, 1, auth_request=True)

        self.assertEqual(caught.exception.category, "unexpected_response_schema")
        self.assertEqual(caught.exception.diagnostic["http_status"], 200)

    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_yi_non_success_code_is_reported_without_server_message(self, urlopen_mock):
        leaked = "TOKEN_SECRET_MUST_NOT_APPEAR"
        urlopen_mock.return_value = FakeResponse(200, json.dumps({"code": 50000, "msg": f"server rejected {leaked}"}).encode())

        with self.assertRaises(probe.YiCloudError) as caught:
            probe.get_json("https://gw-eu.xiaoyi.com", "/v4/devices/list", [], {}, 1)

        error = caught.exception
        self.assertEqual(error.category, "server_rejection")
        self.assertEqual(error.diagnostic["http_status"], 200)
        self.assertEqual(error.diagnostic["yi_code"], 50000)
        self.assertNotIn(leaked, str(error))
        self.assertNotIn(leaked, json.dumps(error.diagnostic))

    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_production_string_code_and_text_html_json_are_accepted(self, urlopen_mock):
        payload = production_login_response()
        urlopen_mock.return_value = FakeResponse(
            200,
            json.dumps(payload).encode(),
            {"Content-Type": "text/html; charset=utf-8"},
        )

        response, request_diagnostic = probe.get_json(
            "https://gw-eu.xiaoyi.com",
            "/v4/users/login",
            [],
            {},
            1,
            auth_request=True,
        )

        self.assertEqual(response, payload)
        self.assertEqual(request_diagnostic["yi_code"], 20000)
        self.assertTrue(request_diagnostic["ok"])

    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_integer_success_code_remains_supported(self, urlopen_mock):
        payload = production_login_response(code=20000, userid="12345678")
        urlopen_mock.return_value = FakeResponse(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})

        response, request_diagnostic = probe.get_json("https://gw-eu.xiaoyi.com", "/v4/users/login", [], {}, 1, auth_request=True)

        self.assertEqual(response["code"], 20000)
        self.assertEqual(request_diagnostic["yi_code"], 20000)

    def test_userid_normalizes_integer_and_preserves_string(self):
        self.assertEqual(probe._user_id(12345678), "12345678")
        self.assertEqual(probe._user_id("12345678"), "12345678")
        self.assertIsNone(probe._user_id(""))
        self.assertIsNone(probe._user_id(True))

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "pw"))
    def test_live_shape_integer_userid_and_string_register_time_reach_device_signature(self, _credentials_mock):
        calls = []

        def fake_get_json(host, path, params, headers, timeout, **kwargs):
            calls.append((path, params))
            if path == "/v4/users/login":
                return production_login_response(), diagnostic(path)
            return camera_response(), diagnostic(path)

        with mock.patch.object(probe, "get_json", side_effect=fake_get_json):
            report = probe.run(cli_args())

        self.assertTrue(report["ok"])
        self.assertEqual(dict(calls[1][1])["userid"], "12345678")
        self.assertIsInstance(production_login_response()["data"]["register_time"], str)

    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_malformed_and_non_success_codes_remain_rejected(self, urlopen_mock):
        cases = ("20000 ", "success", 20000.0, True, None, "50000", 50000)
        for code in cases:
            with self.subTest(code=code):
                urlopen_mock.return_value = FakeResponse(
                    200,
                    json.dumps(production_login_response(code=code)).encode(),
                    {"Content-Type": "application/json"},
                )
                with self.assertRaises(probe.YiCloudError):
                    probe.get_json("https://gw-eu.xiaoyi.com", "/v4/users/login", [], {}, 1, auth_request=True)

    def test_response_shape_reports_wrappers_without_secret_values(self):
        secret = "FAKE_SECRET_ANYWHERE_MUST_NOT_APPEAR"
        raw = json.dumps(
            {
                "code": "20000",
                "message": secret,
                "reason": 123456,
                "error": {"reason": secret},
                "data": {"token": secret, "token_secret": secret, "password": secret},
                "result": {
                    "code": 20000,
                    "msg": secret,
                    "payload": {"authorization": secret, "cookie": secret},
                    "body": json.dumps({"message": secret, "data": {"camera_password": secret}}),
                },
            }
        ).encode()

        shape = probe.response_shape(raw, {"Content-Type": "application/json; charset=UTF-8"})
        rendered = json.dumps(shape)

        self.assertNotIn(secret, rendered)
        self.assertEqual(shape["content_type"], "application/json; charset=utf-8")
        self.assertEqual(shape["body_length"], len(raw))
        self.assertEqual(shape["body_sha256"], probe.hashlib.sha256(raw).hexdigest())
        self.assertTrue(shape["utf8"])
        self.assertTrue(shape["json_parse"])
        self.assertEqual(shape["json_type"], "object")
        self.assertEqual(shape["keys"]["result"], "object")
        self.assertEqual(shape["code"], {"type": "string", "value": "20000"})
        self.assertEqual(shape["sanitized_messages"]["message"]["value"], "<redacted>")
        self.assertEqual(shape["sanitized_messages"]["reason"]["value"], "<redacted>")
        self.assertEqual(shape["nested_shapes"]["data"]["keys"]["token"], "string")
        self.assertEqual(shape["nested_shapes"]["result"]["nested_shapes"]["body"]["string_json_type"], "object")

    def test_response_shape_second_parses_a_json_string(self):
        secret = "SECOND_PARSE_SECRET_MUST_NOT_APPEAR"
        raw = json.dumps(json.dumps({"code": "20000", "data": {"token": secret}})).encode()

        shape = probe.response_shape(raw, {"Content-Type": "application/json"})

        self.assertEqual(shape["json_type"], "string")
        self.assertTrue(shape["second_json_parse"])
        self.assertEqual(shape["second_json_type"], "object")
        self.assertEqual(shape["second_json_shape"]["keys"]["data"], "object")
        self.assertNotIn(secret, json.dumps(shape))

    def test_response_shape_classifies_html_without_printing_body(self):
        secret = "HTML_SECRET_MUST_NOT_APPEAR"
        raw = f"<!doctype html><html><head><title>{secret}</title></head></html>".encode()

        shape = probe.response_shape(raw, {"Content-Type": "text/html", "Set-Cookie": f"session={secret}"})

        self.assertEqual(shape["response_kind"], "html_or_xml")
        self.assertFalse(shape["json_parse"])
        self.assertNotIn(secret, json.dumps(shape))

    def test_response_shape_observes_undecoded_gzip_without_decoding(self):
        secret = "GZIP_SECRET_MUST_NOT_APPEAR"
        raw = gzip.compress(json.dumps({"code": 20000, "token": secret}).encode())

        shape = probe.response_shape(raw, {"Content-Type": "application/json", "Content-Encoding": "gzip"})

        self.assertEqual(shape["content_encoding"], "gzip")
        self.assertEqual(shape["body_magic"], "gzip")
        self.assertEqual(shape["content_encoding_observation"], "gzip_bytes_remain_after_urllib_read")
        self.assertFalse(shape["utf8"])
        self.assertFalse(shape["json_parse"])
        self.assertNotIn(secret, json.dumps(shape))

    def test_device_array_shape_reports_types_and_failures_without_values(self):
        secrets = {
            "uid": "UID_VALUE_MUST_NOT_APPEAR",
            "did": "DID_VALUE_MUST_NOT_APPEAR",
            "password": "PASSWORD_VALUE_MUST_NOT_APPEAR",
            "ip": "IP_VALUE_MUST_NOT_APPEAR",
            "mac": "MAC_VALUE_MUST_NOT_APPEAR",
            "ssid": "SSID_VALUE_MUST_NOT_APPEAR",
            "account": "ACCOUNT_VALUE_MUST_NOT_APPEAR",
            "token": "TOKEN_VALUE_MUST_NOT_APPEAR",
            "token_secret": "TOKEN_SECRET_VALUE_MUST_NOT_APPEAR",
        }
        ipc = {
            "p2p_encrypt": True,
            "ssid": secrets["ssid"],
            "mac": secrets["mac"],
            "ip": secrets["ip"],
            "rssi": -50,
            "smartservice": False,
            "signal_quality": "good",
            "signalQuality": "good",
            "battery": "0",
            "batteryLevel": "0",
            "battery_chg": "0",
            "wakeup": False,
        }
        camera = {
            "uid": secrets["uid"],
            "did": secrets["did"],
            "model": "6",
            "name": "CAMERA_NAME_MUST_NOT_APPEAR",
            "message": "MESSAGE_VALUE_MUST_NOT_APPEAR",
            "flag": False,
            "share": False,
            "hasPincode": False,
            "category": 0,
            "count": 0,
            "nickname": "NICKNAME_VALUE_MUST_NOT_APPEAR",
            "type": "0",
            "accessRight": 0,
            "accessCount": 0,
            "sharedBy": 0,
            "sharedTime": 0,
            "lastAccessTime": 0,
            "online": True,
            "state": 1,
            "password": secrets["password"],
            "groupBindable": 0,
            "ipcParam": json.dumps(ipc),
            "account": secrets["account"],
            "token": secrets["token"],
            "token_secret": secrets["token_secret"],
            "appParam": {
                "server": "TNP_SERVER_VALUE_MUST_NOT_APPEAR",
                "credentials": {
                    "license": "TNP_LICENSE_VALUE_MUST_NOT_APPEAR",
                    "device_key": "TNP_DEVICE_KEY_VALUE_MUST_NOT_APPEAR",
                },
            },
        }
        payload = {
            "code": "20000",
            "data": [
                camera,
                {"ipcParam": ipc},
                {"ipcParam": "not-json-INNER_SECRET_MUST_NOT_APPEAR"},
                "ARRAY_ELEMENT_SECRET_MUST_NOT_APPEAR",
                {"ipcParam": "{}"},
            ],
        }

        shape = probe.response_shape(
            json.dumps(payload).encode(),
            {"Content-Type": "application/json"},
            "/v4/devices/list",
        )
        rendered = json.dumps(shape)

        self.assertEqual(shape["array_count"], 5)
        first = shape["array_elements"][0]
        self.assertEqual(first["index"], 0)
        self.assertEqual(first["type"], "object")
        self.assertEqual(first["keys"]["uid"], "string")
        self.assertEqual(first["keys"]["type"], "string")
        self.assertEqual(first["ipcParam_shape"]["outer_type"], "string")
        self.assertTrue(first["ipcParam_shape"]["json_parse"])
        self.assertEqual(first["ipcParam_shape"]["inner_type"], "object")
        self.assertEqual(first["ipcParam_shape"]["keys"]["ip"], "string")
        self.assertEqual(first["appParam_shape"]["outer_type"], "object")
        self.assertEqual(first["appParam_shape"]["inner_shape"]["keys"]["server"], "string")
        self.assertEqual(
            first["appParam_shape"]["inner_shape"]["nested"]["credentials"]["keys"]["license"],
            "string",
        )
        self.assertIn(
            {"field": "type", "expected": ["integer"], "actual_json_type": "string"},
            first["parser_failures"],
        )
        second = shape["array_elements"][1]
        self.assertEqual(second["ipcParam_shape"]["representation"], "already_object")
        self.assertEqual(second["parser_validation"], "no_failures_for_present_fields")
        third = shape["array_elements"][2]
        self.assertIn({"field": "ipcParam", "reason": "inner_json_parse_failed"}, third["parser_failures"])
        fourth = shape["array_elements"][3]
        self.assertEqual(fourth["parser_failures"][0]["actual_json_type"], "string")
        fifth = shape["array_elements"][4]
        self.assertEqual(fifth["parser_validation"], "no_failures_for_present_fields")
        self.assertIn("uid", fifth["missing_documented_fields"])
        self.assertIn("account", first["additional_fields"])
        for secret in (
            *secrets.values(),
            "CAMERA_NAME_MUST_NOT_APPEAR",
            "INNER_SECRET_MUST_NOT_APPEAR",
            "ARRAY_ELEMENT_SECRET_MUST_NOT_APPEAR",
            "TNP_SERVER_VALUE_MUST_NOT_APPEAR",
            "TNP_LICENSE_VALUE_MUST_NOT_APPEAR",
            "TNP_DEVICE_KEY_VALUE_MUST_NOT_APPEAR",
        ):
            self.assertNotIn(secret, rendered)

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "RAW_LOGIN_PASSWORD_MUST_NOT_APPEAR"))
    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_device_array_debug_stdout_and_saved_report_never_contain_values(self, urlopen_mock, _credentials_mock):
        uid = "LIVE_UID_VALUE_MUST_NOT_APPEAR"
        did = "LIVE_DID_VALUE_MUST_NOT_APPEAR"
        camera_password = "LIVE_CAMERA_PASSWORD_MUST_NOT_APPEAR"
        ip = "LIVE_IP_VALUE_MUST_NOT_APPEAR"
        mac = "LIVE_MAC_VALUE_MUST_NOT_APPEAR"
        ssid = "LIVE_SSID_VALUE_MUST_NOT_APPEAR"
        devices = {
            "code": "20000",
            "data": [
                {
                    "uid": uid,
                    "did": did,
                    "password": camera_password,
                    "ipcParam": {"ip": ip, "mac": mac, "ssid": ssid, "p2p_encrypt": "not-boolean"},
                }
            ],
        }
        urlopen_mock.side_effect = [
            FakeResponse(200, json.dumps(production_login_response()).encode(), {"Content-Type": "text/html; charset=utf-8"}),
            FakeResponse(200, json.dumps(devices).encode(), {"Content-Type": "application/json"}),
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "device-array-shape.json")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = probe.main(
                    [
                        "discover",
                        "--region",
                        "eu",
                        "--country",
                        "IL",
                        "--account",
                        "person@example.com",
                        "--device-brand",
                        "samsung",
                        "--device-model",
                        "SM-S901B",
                        "--android-version",
                        "13",
                        "--language",
                        "en-US",
                        "--debug-response-shape",
                        "--save-report",
                        str(path),
                    ]
                )
            output = stdout.getvalue()
            saved = path.read_text(encoding="utf-8")

        self.assertEqual(code, 1)
        self.assertIn('"array_count": 1', output)
        self.assertIn('"representation": "already_object"', output)
        self.assertIn('"parser_failures"', output)
        for secret in (uid, did, camera_password, ip, mac, ssid, LOGIN_TOKEN, TOKEN_SECRET, "RAW_LOGIN_PASSWORD_MUST_NOT_APPEAR"):
            self.assertNotIn(secret, output)
            self.assertNotIn(secret, saved)

    def test_production_ipc_object_and_canonical_boolean_string_are_parsed(self):
        camera = camera_response()["data"][0]
        camera["password"] = ""
        camera["ipcParam"] = {
            "ip": "192.0.2.1",
            "mac": "00:00:00:00:00:00",
            "p2p_encrypt": "false",
            "ssid": "test",
        }

        summary = probe.camera_summary(camera, 1, False)

        self.assertFalse(summary["ipcParam"]["p2p_encrypt"])
        camera["ipcParam"]["p2p_encrypt"] = "TRUE"
        self.assertTrue(probe.camera_summary(camera, 1, False)["ipcParam"]["p2p_encrypt"])

    def test_noncanonical_p2p_encrypt_string_is_rejected(self):
        camera = camera_response()["data"][0]
        camera["ipcParam"] = {"p2p_encrypt": "1"}

        with self.assertRaises(probe.YiCloudError):
            probe.camera_summary(camera, 1, False)

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "RAW_LOGIN_PASSWORD_MUST_NOT_APPEAR"))
    @mock.patch.object(probe.urllib.request, "urlopen")
    def test_debug_shape_stdout_and_saved_report_never_contain_response_secrets(self, urlopen_mock, _credentials_mock):
        secret = "RESPONSE_SECRET_MUST_NOT_APPEAR"
        raw = json.dumps(
            {
                "code": "20000",
                "msg": secret,
                "data": {
                    "token": secret,
                    "token_secret": secret,
                    "password": secret,
                    "cookie": secret,
                    "authorization": secret,
                },
            }
        ).encode()
        urlopen_mock.return_value = FakeResponse(
            200,
            raw,
            {
                "Content-Type": f"application/{secret}",
                "Content-Encoding": secret,
                "Set-Cookie": f"session={secret}",
                "Authorization": secret,
            },
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "shape-report.json")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = probe.main(
                    [
                        "login",
                        "--region",
                        "eu",
                        "--country",
                        "IL",
                        "--account",
                        "person@example.com",
                        "--device-brand",
                        "samsung",
                        "--device-model",
                        "SM-S901B",
                        "--android-version",
                        "13",
                        "--language",
                        "en-US",
                        "--debug-response-shape",
                        "--save-report",
                        str(path),
                    ]
                )
            output = stdout.getvalue()
            saved = path.read_text(encoding="utf-8")

        transformed = probe.password_transform("RAW_LOGIN_PASSWORD_MUST_NOT_APPEAR")
        self.assertEqual(code, 1)
        self.assertIn('"error_category": "unexpected_response_schema"', output)
        for forbidden in (secret, "RAW_LOGIN_PASSWORD_MUST_NOT_APPEAR", transformed, "session="):
            self.assertNotIn(forbidden, output)
            self.assertNotIn(forbidden, saved)

    @mock.patch.object(probe, "credentials", return_value=("person@example.com", "pw"))
    @mock.patch.object(probe, "get_json", side_effect=successful_get_json)
    def test_explicit_saved_report_is_sanitized(self, _get_json_mock, _credentials_mock):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "report.json")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = probe.main(
                    [
                        "discover",
                        "--region",
                        "eu",
                        "--country",
                        "IL",
                        "--account",
                        "person@example.com",
                        "--device-brand",
                        "samsung",
                        "--device-model",
                        "SM-S901B",
                        "--android-version",
                        "13",
                        "--language",
                        "en-US",
                        "--save-report",
                        str(path),
                    ]
                )
            saved = path.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        for secret in (LOGIN_TOKEN, TOKEN_SECRET, CAMERA_PASSWORD, ENCRYPTED_PASSWORD, UID, "DID-MUST-BE-REDACTED"):
            self.assertNotIn(secret, saved)

    def test_cli_has_no_show_secrets_flag(self):
        self.assertNotIn("--show-secrets", probe.parser().format_help())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            probe.parser().parse_args(["discover", "--show-secrets"])


if __name__ == "__main__":
    unittest.main()
