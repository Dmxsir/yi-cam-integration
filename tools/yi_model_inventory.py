#!/usr/bin/env python3
"""Print a secret-safe model inventory for cameras in the configured YI account.

This intentionally omits UID, DID, IP/MAC, encrypted password, license,
InitString, tokens and all auth material. ``interVersion`` is shown only as a
cloud-reported version-like field; its exact semantics are not assumed to be
the authoritative running firmware version.

Model resolution keeps evidence sources separate:
- APK feature_config registry is authoritative for mappings present in the APK.
- Supplemental external evidence is used only for an exact raw-model + cloud
  version match. It can either resolve a missing APK mapping or add a marketing
  name / firmware-family cross-check to an already-known mapping.

The cloud ``online`` field is deliberately reported as ``cloud_online_reported``.
It may be stale and must not be treated as an authoritative reachability signal.
A later native PPPP Connect/Check result is the authoritative runtime signal.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yi_cloud_probe as cloud
import yi_model_evidence as external_evidence
import yi_model_registry as registry
import yi_tnp_oracle as oracle


def required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    oracle.load_env_file(args.env_file)
    region = os.getenv("YI_REGION", "eu").casefold()
    country = required("YI_COUNTRY").upper()
    if region != "eu" or country != "IL":
        raise RuntimeError("Inventory is restricted to the configured EU/IL account")

    host = cloud.GATEWAY_HOSTS[region]
    headers = cloud.request_headers(
        country,
        required("YI_DEVICE_MODEL"),
        required("YI_ANDROID_VERSION"),
        required("YI_LANGUAGE"),
    )
    login, _ = cloud.get_json(
        host,
        "/v4/users/login",
        cloud.login_params(
            region,
            required("YI_ACCOUNT"),
            required("YI_PASSWORD"),
            required("YI_DEVICE_BRAND"),
            required("YI_DEVICE_MODEL"),
            required("YI_ANDROID_VERSION"),
        ),
        headers,
        args.timeout,
        auth_request=True,
    )
    data = login.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected login schema")
    user_id = cloud._user_id(data.get("userid"))
    token = data.get("token")
    token_secret = data.get("token_secret")
    if user_id is None or not isinstance(token, str) or not token or not isinstance(token_secret, str) or not token_secret:
        raise RuntimeError("Required live authentication state is unavailable")

    devices, _ = cloud.get_json(
        host,
        "/v4/devices/list",
        cloud.device_list_params(user_id, token, token_secret),
        headers,
        args.timeout,
    )
    cameras = devices.get("data")
    if not isinstance(cameras, list) or not all(isinstance(item, dict) for item in cameras):
        raise RuntimeError("Unexpected devices/list schema")

    print("yi_model_inventory=START")
    print(f"camera_count={len(cameras)}")
    print("secret_fields_logged=false")
    print("firmware_note=cloud_inter_version_is_version_like_only_not_authoritative_firmware")
    print("online_note=cloud_online_reported_may_be_stale_use_native_pppp_reachability_for_runtime_status")
    print("resolution_policy=apk_registry_plus_exact_raw_model_and_cloud_version_external_crosscheck")

    for index, camera in enumerate(cameras):
        raw_model = str(camera.get("model", ""))
        did = camera.get("did")
        inter_version = camera.get("interVersion")
        if not isinstance(inter_version, (str, int, float)) or isinstance(inter_version, bool):
            inter_version = "UNKNOWN"

        registry_model, registry_evidence = registry.resolve(raw_model, did)
        candidates = registry.candidates(raw_model, did)
        apk_candidate_models = ",".join(sorted({item.model for item in candidates})) or "UNKNOWN"
        branches = ",".join(sorted({item.firmware_branch for item in candidates if item.firmware_branch})) or "UNKNOWN"

        supplemental = external_evidence.resolve(raw_model, inter_version)
        if registry_model != "UNKNOWN":
            resolved = registry_model
            resolution_evidence = registry_evidence
            if supplemental is not None and supplemental.model != registry_model:
                resolution_evidence += "+external_conflict"
            marketing_name = supplemental.marketing_name if supplemental is not None else "UNKNOWN"
            supplemental_evidence = supplemental.evidence if supplemental is not None else "NONE"
            evidence_sources = "APK_feature_config"
            if supplemental is not None:
                evidence_sources += "," + ",".join(supplemental.sources)
        elif supplemental is not None:
            resolved = supplemental.model
            resolution_evidence = supplemental.evidence
            marketing_name = supplemental.marketing_name
            supplemental_evidence = supplemental.evidence
            evidence_sources = ",".join(supplemental.sources)
        else:
            resolved = "UNKNOWN"
            resolution_evidence = registry_evidence
            marketing_name = "UNKNOWN"
            supplemental_evidence = "NONE"
            evidence_sources = "NONE"

        print(f"camera[{index}].name={str(camera.get('name', ''))}")
        print(f"camera[{index}].raw_model={raw_model}")
        print(f"camera[{index}].resolved_model={resolved}")
        print(f"camera[{index}].resolution_evidence={resolution_evidence}")
        print(f"camera[{index}].marketing_name={marketing_name}")
        print(f"camera[{index}].apk_candidate_models={apk_candidate_models}")
        print(f"camera[{index}].firmware_branches={branches}")
        print(f"camera[{index}].cloud_inter_version={inter_version}")
        print(f"camera[{index}].supplemental_evidence={supplemental_evidence}")
        print(f"camera[{index}].evidence_sources={evidence_sources}")
        print(f"camera[{index}].p2p_type={camera.get('type')}")
        print(f"camera[{index}].cloud_online_reported={camera.get('online') is True}")

    # Drop references to account session secrets before normal exit.
    token = token_secret = ""
    login = devices = data = cameras = None
    print("yi_model_inventory=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
