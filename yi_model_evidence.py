"""Supplemental version-aware YI camera model evidence.

This module is deliberately separate from :mod:`yi_model_registry`: the latter
contains APK-derived ``feature_config`` mappings, while this file records
external observations that are useful for marketing-name and firmware-family
cross-checks, especially when a newer cloud raw model is absent from the
analyzed APK.

Only exact raw-model + cloud-version matches are recorded here. This prevents a
community observation for one firmware line from being silently generalized to
all devices that happen to share a raw model.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExternalModelEvidence:
    raw_model: str
    cloud_version: str
    model: str
    marketing_name: str
    evidence: str
    sources: tuple[str, ...]


_EXTERNAL: dict[tuple[str, str], ExternalModelEvidence] = {
    (
        "89",
        "12.0.51.08_202411131107",
    ): ExternalModelEvidence(
        raw_model="89",
        cloud_version="12.0.51.08_202411131107",
        model="y623",
        marketing_name="YI Home 2K Pro / YI Pro 2K Home",
        evidence="external_exact_firmware_match",
        sources=(
            "roleoroleo/yi-hack-Allwinner-v2#1102",
            "roleoroleo/yi-hack-Allwinner-v2#1115",
        ),
    ),
    (
        "83",
        "12.0.35.8_202607170948",
    ): ExternalModelEvidence(
        raw_model="83",
        cloud_version="12.0.35.8_202607170948",
        model="y291ga",
        marketing_name="YI 1080p Home",
        evidence="external_firmware_family_crosscheck",
        sources=(
            "roleoroleo/yi-hack-Allwinner-v2 README: YI 1080p Home / 12.0.35* / y291ga",
        ),
    ),
    (
        "51",
        "9.0.19.12_202102241808",
    ): ExternalModelEvidence(
        raw_model="51",
        cloud_version="9.0.19.12_202102241808",
        model="y21ga",
        marketing_name="YI 1080p Home / YI Home 1080 AI+",
        evidence="external_exact_firmware_crosscheck",
        sources=(
            "roleoroleo/yi-hack-Allwinner-v2#855",
            "YI/Kami community firmware report for YI Home 1080 AI+",
        ),
    ),
    (
        "40",
        "8.1.0.0A_202001211401",
    ): ExternalModelEvidence(
        raw_model="40",
        cloud_version="8.1.0.0A_202001211401",
        model="y30ga",
        marketing_name="YI Dome X / YYS.3017 family",
        evidence="external_exact_firmware_marketing_crosscheck",
        sources=(
            "roleoroleo/yi-hack-Allwinner-v2#1093",
            "YI/Kami community Dome X firmware report",
        ),
    ),
}


def resolve(raw_model: object, cloud_version: object) -> ExternalModelEvidence | None:
    raw = "" if raw_model is None else str(raw_model)
    version = "" if cloud_version is None else str(cloud_version)
    return _EXTERNAL.get((raw, version))


def all_evidence() -> tuple[ExternalModelEvidence, ...]:
    return tuple(_EXTERNAL[key] for key in sorted(_EXTERNAL))
