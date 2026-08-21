# TNP cloud metadata and model resolution

This document covers the cloud-side inputs for the APK's type-2/TNP path. It
does not describe or perform a PPPP connection. Secret values observed during
controlled validation are intentionally omitted.

## Model resolution

The APK does not contain one hard-coded server-model switch. Class
`com.ants360.yicamera.feature.b` loads `assets/feature_config/config_base.json`
and every `config_*.json` in the same directory. For an ordinary entry it maps
`serverModel` to `model`. Entries whose `serverModel` is `10000` are selected by
an identifier derived from the first five characters of the device DID.

The probe now builds its mapping from those APK assets. If two assets make a
numeric mapping ambiguous, or no asset provides the number, the result is
`UNKNOWN`; it does not use the APK UI's unrelated `y25` fallback.

| Cloud `model` | APK asset model | Evidence |
|---:|---|---|
| `5` | `h20` | feature-config asset |
| `6` | `yunyi.camera.y20` | feature-config asset |
| `40` | `y30ga` | feature-config asset |
| `51` | `y21ga` | feature-config asset |
| `83` | `y291ga` | feature-config asset |
| `89` | `UNKNOWN` | no matching asset in this APK |

The implementation is in `yi_cloud_probe._apk_model_mappings()` and reads an
extracted `.analysis/apk` tree when present, otherwise the APK ZIP directly.

## Production inventory observed on 2026-08-21

The authorized EU/IL discovery returned seven devices. All seven were type `2`
(TNP), online, `p2p_encrypt=true`, and had a recoverable camera password. The
passwords are not recorded here.

| # | Name retained in notes | Cloud UID | Raw model | Normalized model | Type |
|---:|---|---|---:|---|---:|
| 1 | not retained | `<REDACTED_TNP_DID>` | `89` | `UNKNOWN` | 2 |
| 2 | not retained | `<REDACTED_TNP_DID>` | `83` | `y291ga` | 2 |
| 3 | not retained | `<REDACTED_TNP_DID>` | `40` | `y30ga` | 2 |
| 4 | not retained | `<REDACTED_TNP_DID>` | `89` | `UNKNOWN` | 2 |
| 5 | Living room | `<REDACTED_TNP_DID>` | `5` | `h20` | 2 |
| 6 | patio | `<REDACTED_TNP_DID>` | `51` | `y21ga` | 2 |
| 7 | pool | `<REDACTED_TNP_DID>` | `83` | `y291ga` | 2 |

UIDs are included because they are non-password connection identifiers needed
for the next controlled phase. Cloud DIDs, LAN details, tokens, encrypted and
decrypted passwords, cookies, TNP initialization strings, and license values
are not included.

### `appParam`

Six production entries returned `appParam` as an object containing only
`schedule_power`. Its nested on/off records used `enable` (number), `repeater`
(string), and `time` (string). One entry returned a string that was not parsed as
JSON by the safe shape diagnostic. No value was printed or retained.

The legacy `DeviceInfo` parser in `com.ants360.yicamera.db.j` does not consume
`appParam` for TNP connection setup. A separate settings bean
(`com.ants360.yicamera.bean.r`) treats it as optional application configuration.
No observed `appParam` key supplies the TNP DID, initialization string, license,
device key, password, or header version.

## `/v4/tnp/device_info`

### Request contract

| Property | Proven value |
|---|---|
| Method | `GET` |
| EU URL | `https://gw-eu.xiaoyi.com/v4/tnp/device_info` |
| Body | none |
| Signed inputs | `seq=1`, `userid=<login userid>`, `uid=<cloud UID>` |
| HMAC key | `<token>&<token_secret>` |
| HMAC | Base64(HMAC-SHA1(UTF-8 key, UTF-8 canonical parameters)) |

The canonical signing order is exact:

```text
seq=1&userid=<userid>&uid=<cloud UID>
```

The query contains those fields plus `hmac`. The APK later places parameters in
a concurrent map, so URL serialization order is not treated as a protocol
guarantee; the canonical HMAC order is the important part.

The request uses the same regional gateway and common headers as the other YI
cloud calls:

```text
x-kamihome-appType: ANDROID
x-kamihome-packageType: RELEASE
x-xiaoyi-appCountryCode: <explicit country>
x-xiaoyi-appVersion: <explicit app version>
User-Agent: <explicitly configured value>
```

Static request builders are
`com.ants360.yicamera.e.g.m(userid, uid, callback)` and
`com.ants360.yicamera.e.a.d.e(userid, uid, token, tokenSecret)`. The probe's
equivalent is `tnp_device_info_params()`.

### Response contract

Controlled validation of one `y21ga` returned HTTP 200, top-level code string
`"20000"`, and an object under `data` with exactly these key names:

| Key | JSON type | Use in APK |
|---|---|---|
| `DID` | string | Becomes `P2PDevice.p2pid`, passed as the first native connect argument. |
| `InitString` | string | Becomes `tnpServerString`, passed as the fourth native connect argument. |
| `License` | string | Stored whole; its first colon-delimited component becomes `tnpLicenseDeviceKey`, passed as the fifth native connect argument. |

All three values were non-empty for the tested `y21ga`. The license contained
two colon-delimited components. The meaning of the second component is
**UNKNOWN**. No TNP header-version field was present.

The endpoint and APK both use the login `userid` as a string in signed
parameters even when production login returned it as a JSON number. Production
string code `"20000"` is normalized only after strict decimal validation.

### When the APK calls it

1. After `/v4/devices/list`, `com.ants360.yicamera.db.j.P()` loads any cached
   TNP fields and proactively refreshes this endpoint for every device.
2. `CameraPlayerFragment` retries the lookup after PPPP error `-3007` or `-3023`
   (server resolution / invalid initialization data paths), then calls
   `updateTnpConnectInfo`.
3. `ConnectionForBarcodeActivity` follows the same recovery pattern, updates
   cache and `DeviceInfo`, then reconnects.
4. The player integration adapter in `com.ants360.yicamera.a` and a YiPlayer
   recovery path use cached data first, otherwise request a refresh.

The cache keys are `TNP_DID_PREFIX_<uid>`, `TNP_SEV_PREFIX_<uid>`, and
`TNP_KEY_PREFIX_<uid>`. The probe does not create this cache and never persists
tokens or TNP secret material.

## Source-to-connection mapping

| Connection value | Cloud source | Transformation |
|---|---|---|
| Cloud UID | `/v4/devices/list.data[].uid` | Used as cache/identity key, not substituted for a refreshed TNP DID. |
| Camera password | encrypted `devices/list` password | AES-ECB recovery keyed by first 16 UID characters; retained only in memory. |
| `p2p_encrypt` | `devices/list.data[].ipcParam.p2p_encrypt` | Strict bool or `"true"`/`"false"`; selects nonce/HMAC command authentication and frame decryption. |
| PPPP DID | `tnp/device_info.data.DID` | Stored as `DeviceInfo.e` / `P2PDevice.p2pid`. |
| Server/init string | `tnp/device_info.data.InitString` | Passed unchanged to native connect. |
| License device key | first component of `data.License` | Passed to native connect; raw value is secret-safe and never reported. |
| Header version | not cloud-provided | Starts provisionally at 2 and is detected from the first command response. |

## Safe probe command

`tnp-info` performs login, device discovery, and one TNP metadata lookup in one
process. It reports only key names, types, availability booleans, and component
counts. It never reports `DID`, `InitString`, `License`, its device-key
component, tokens, or camera passwords.

```powershell
python yi_cloud_probe.py tnp-info --region eu --camera-index 6 --debug-response-shape --show-uid
```

This command was used for the cloud-only validation above. It does not load or
call `libPPPP_API.so`.
