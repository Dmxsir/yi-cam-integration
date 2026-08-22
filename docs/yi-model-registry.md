# YI raw-model / camera-family registry

## Why this is a first-class project concern

The cloud `/v4/devices/list` field named `model` is a **raw server-model
discriminator**, not necessarily the final camera model name.  The YI Home APK
maps it through `assets/feature_config/config_*.json`, where `serverModel`
corresponds to the cloud value and `model` is the normalized camera family.

The bridge must therefore keep a registry rather than hard-code one camera.
This is especially important across different camera hardware and firmware
families.

## Current evidence set

The checked-in `yi_model_registry.py` is derived from YI Home
`5.6.5_20220819031350` (version code 319, SHA-256
`776967311D74F2AC94FC91D3FA7AEDEA16B2023DAF9D14468931FA13EEF4F227`).
It contains 54 feature-config mappings covering 50 distinct raw/server-model
values.

For each candidate we retain mapping-related metadata:

- raw/server model (`serverModel`)
- normalized camera model (`model`)
- APK `firmwareBranch`
- `identifier` for identifier-based models
- feature-config/base versions
- platform/device type
- online-P2P capability
- power-supply type
- H.265 capability
- source feature-config filename

`tools/extract_yi_model_registry.py` can extract the same metadata from another
YI Home APK so newer app releases can be compared and merged instead of
silently assuming the 2022 table is permanent.

## Important ambiguity: raw model is not always one-to-one

The inspected APK contains these ambiguous server models:

| raw model | candidates | extra evidence required |
|---:|---|---|
| 43 | `h31gc`, `y32gc` | raw model alone is insufficient; firmware/hardware-family evidence must disambiguate |
| 64 | `w102`, `w12ga` | both use firmware branch `familymonitor-w12ga`; treat as aliases/candidates until stronger device evidence is available |
| 65 | `w102`, `w102s` | both use firmware branch `familymonitor-w102s`; treat as aliases/candidates until stronger device evidence is available |
| 10000 | `iotk2`, `iotv3` | APK explicitly resolves with the first five characters of `did`: `A0016` -> `iotk2`, `A0010` -> `iotv3` |

A resolver must return `UNKNOWN`/candidate-set for an ambiguous raw model rather
than guess.

## Examples from the current registry

| raw model | normalized model | firmware branch |
|---:|---|---|
| 6 | `yunyi.camera.y20` | not declared in this APK config |
| 38 | `y20ga` | `familymonitor-y20ga` |
| 40 | `y30ga` | `familymonitor-y30qa` |
| 46 | `y29ga` | `familymonitor-y29ga` |
| 51 | `y21ga` | `familymonitor-y21ga` |
| 55 | `y28ga` | `familymonitor-y28ga` |
| 66 | `y281ga` | `familymonitor-y281ga` |
| 67 | `y211ga` | `familymonitor-y211ga` |
| 72 | `y26ga` | `familymonitor-y26ga` |
| 83 | `y291ga` | `familymonitor-y291ga` |
| 84 | `y311ga` | `familymonitor-y311ga` |

The full table is represented in code by `yi_model_registry.py`; do not use this
short example table as the resolver.

## Firmware version is a separate axis

`/v4/devices/list` does **not** provide the authoritative running firmware
version used by the old app's device-info path.  `firmwareBranch` in the APK is
a feature/model-family branch label, not proof of which firmware is currently
installed on a camera.

For a robust multi-camera bridge we need to retain both:

1. **identity/model evidence**: raw model, normalized candidate(s), DID-prefix
   rule where applicable, cloud P2P type, and APK firmware branch metadata;
2. **runtime firmware evidence**: the actual version returned after connection
   by the relevant device-info/pre-version control response.

That separation prevents firmware differences from being mistaken for a new
raw camera model, and prevents one raw model from being incorrectly assumed to
have one firmware behavior forever.

## Runtime policy

- Never infer a unique model from an ambiguous raw model without additional
  evidence.
- Record the source/evidence used for each resolution (`registry_unique`,
  `registry_identifier`, firmware/hardware evidence, or `UNKNOWN`).
- Keep protocol capability decisions separate from cosmetic model names.
- For TNP cameras, verify behavior/capabilities at runtime where possible rather
  than relying only on old APK metadata.
- When a new APK is analyzed, extract its feature configs and diff the registry;
  do not overwrite historical mappings without provenance.
