"""Supplemental version-aware YI camera model evidence.

This module is deliberately separate from :mod:`yi_model_registry`: the latter
contains APK-derived ``feature_config`` mappings, while this file records
external observations that are useful when a newer cloud raw model is absent
from the analyzed APK.

Only exact raw-model + cloud-version matches are resolved here.  This prevents a
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
}


def resolve(raw_model: object, cloud_version: object) -> ExternalModelEvidence | None:
    raw = "" if raw_model is None else str(raw_model)
    version = "" if cloud_version is None else str(cloud_version)
    return _EXTERNAL.get((raw, version))


def all_evidence() -> tuple[ExternalModelEvidence, ...]:
    return tuple(_EXTERNAL[key] for key in sorted(_EXTERNAL))
