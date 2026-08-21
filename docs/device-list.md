# Camera discovery: `/v4/devices/list`

## Request

The active builder is `com.ants360.yicamera.e.a.d.d(userid)`. The caller is `com.ants360.yicamera.db.j.z()`, which obtains the current user ID from `base.ad`.

| Property | Value |
|---|---|
| Method | `GET` |
| URL | `<regional gateway>/v4/devices/list` |
| Body | none |
| Content-Type | none set |
| Timestamp | none |
| Nonce | none |

The signed fields and canonical string are exact:

```text
signed fields, insertion order:
  seq=1
  userid=<login data.userid>

canonical:
  seq=1&userid=<login data.userid>

key:
  <login data.token>&<login data.token_secret>

hmac:
  Base64(HMAC-SHA1(UTF-8(key), UTF-8(canonical)))
```

Final query:

```text
seq=1&userid=<userid>&hmac=<signature>
```

The common app/country/version headers are documented in [cloud-auth.md](cloud-auth.md).

## Top-level response

The HTTP wrapper requires HTTP 200. The app then requires JSON `code == 20000` and treats `data` as an array. Static analysis proves the fields that its parser reads; it cannot prove that the server never includes additional fields.

```json
{
  "code": 20000,
  "data": [
    {
      "uid": "...",
      "did": "...",
      "model": "6",
      "type": 0,
      "password": "hex ciphertext",
      "ipcParam": "{...}"
    }
  ]
}
```

### Confirmed EU production response (2026)

A controlled Phase 2A validation against `https://gw-eu.xiaoyi.com/v4/devices/list` confirmed HTTP 200 with UTF-8 JSON despite response `Content-Type: text/html; charset=utf-8`. Current production returns top-level `code` as the JSON string `"20000"` and `data` as an array.

Every device object in the validated response differed from the APK-derived representation in two parser-relevant ways:

- `ipcParam` was already a JSON object rather than a string containing JSON;
- `ipcParam.p2p_encrypt` was a canonical JSON string boolean rather than a JSON boolean.

The probe now accepts either the APK form or this production form. String booleans are restricted to case-insensitive `"true"`/`"false"`; arbitrary strings are rejected. Optional APK-consumed fields absent from the production objects are not required. The production response also contained additional fields `activeTime`, `appParam`, `interVersion`, `isNew`, `onlineTime`, `relayFlag`, `sdState`, and `webPairStatus`; these are not needed by the Phase 2A parser. `ipcParam.powerstate` was present on some entries and is likewise ignored. No production identifier, network address, encrypted password, or authentication secret is recorded here.

## Every top-level camera field consumed

| JSON field | JSON type used | Destination | Meaning established by code |
|---|---|---|---|
| `uid` | string | `DeviceInfo.UID`, `d`, `e` | Cloud device UID; also becomes the TUTK P2P UID in this parser. |
| `did` | string | `DeviceInfo.f` | Separate device identifier used for model/feature inference and other cloud operations. It is not passed to `IOTC_Connect_ByUID_Parallel`. |
| `model` | string, default `"1"` | normalized to `DeviceInfo.B`; original textual form may be retained in `C` | Cloud/server model discriminator. Numeric `6` maps to `yunyi.camera.y20`. |
| `name` | string | `DeviceInfo.j` | User-facing name. |
| `message` | string | `DeviceInfo.m` | Message field; exact server semantics are not established here. |
| `flag` | boolean | `DeviceInfo.o`; inverse in `n` | Boolean device flag; exact server semantics are not established here. |
| `share` | boolean | `DeviceInfo.p` | Shared-device indicator. |
| `hasPincode` | boolean | `DeviceInfo.U` (`1`/`0`) | Whether the app must obtain the connection password through a PIN-gated lookup. The PIN itself is not returned. |
| `category` | integer, default `0` | `DeviceInfo.Y` | Category. |
| `count` | integer, default `0` | `DeviceInfo.Z` | Count field; exact server semantics are not established here. |
| `nickname` | string, default empty | `DeviceInfo.aa` | Nickname. |
| `type` | integer, default `0` | `DeviceInfo.w` -> `P2PDevice.type` | P2P implementation selector: 0 TUTK, 1 Langtao, 2 TNP. |
| `accessRight` | integer | `DeviceInfo.ab` | Share/access-right value. Bit meanings are outside this trace. |
| `accessCount` | integer | `DeviceInfo.ac` | Access count. |
| `sharedBy` | integer | `DeviceInfo.ad` | Sharing owner/reference value. |
| `sharedTime` | integer | `DeviceInfo.ae` | Share time value. Unit is not established by this parser. |
| `lastAccessTime` | integer | `DeviceInfo.af` | Last-access value. Unit is not established by this parser. |
| `online` | boolean | `DeviceInfo.k` | Cloud-reported online state. |
| `state` | integer | `DeviceInfo.ai` | Device state value. Enumeration is not established by this parser. |
| `password` | string | decrypted to `DeviceInfo.i`, unless PIN-gated | Hex-encoded AES ciphertext when non-empty; see below. |
| `groupBindable` | integer compared with `1` | `DeviceInfo.au` | Group-bind capability. |
| `ipcParam` | string containing JSON | multiple fields below | Additional IPC/P2P/network state. The parser explicitly constructs a second `JSONObject` from this string. |

## `ipcParam` fields consumed

| Field | Type/default | App meaning |
|---|---|---|
| `p2p_encrypt` | boolean, default `true` | Enables encrypted AV authentication and partial I-frame decryption. |
| `ssid` | string, empty | Camera Wi-Fi SSID. |
| `mac` | string, empty | Camera MAC address. |
| `ip` | string, empty | Camera-reported IP/LAN address. |
| `rssi` | integer, `0` | Wi-Fi RSSI. |
| `smartservice` | boolean, `false` | Smart-service flag. |
| `signal_quality` | string, empty | Signal quality, preferred spelling. |
| `signalQuality` | string, empty | Fallback spelling. |
| `battery` | string, `"0"` | Battery value, preferred spelling. |
| `batteryLevel` | string, `"0"` | Fallback spelling. |
| `battery_chg` | string, `"0"` | Battery charging state/value. |
| `wakeup` | boolean, `false` | Wake-up capability/state passed into `P2PDevice`. |

## Model resolution for `yunyi.camera.y20`

`feature.b` loads `config_y20.json`, which declares `serverModel: "6"` and `model: "yunyi.camera.y20"`. `DeviceInfo.b(model,did)` handles the list's model value as follows:

- a one- or two-digit model (including `6`) is looked up in the feature manager;
- model `10000` uses the first five characters of `did` as an identifier lookup;
- a textual value beginning `Y20` normalizes to `yunyi.camera.y20`;
- an unrecognized value follows fallback logic and must not be assumed to be Y20.

## Camera password and PIN behavior

### Non-PIN device

If `password` is empty, `util.f.a(uid)` returns the literal fallback `888888`. The function ignores its `uid` argument.

If `password` is non-empty, it is treated as hexadecimal ciphertext:

```text
key bytes  = default-charset bytes of uid.substring(0, 16)
cipher     = AES/ECB/PKCS7Padding
ciphertext = hex_decode(device.password)
plaintext  = new String(AES_decrypt(key, ciphertext))
```

On Android, `PKCS7Padding` here has the usual AES block-padding behavior commonly called PKCS#5/PKCS#7. The resulting plaintext becomes `DeviceInfo.i` and then `P2PDevice.pwd`.

If a UID is shorter than 16 characters or the ciphertext is malformed, the parser can fail and logs an exception. No alternative key derivation was found.

### PIN-gated device

When `hasPincode == true`, the list parser deliberately sets the connection password to an empty string even if a `password` field was present. It does not contain or recover the user's PIN.

After a PIN is entered, the cloud implementation calls:

```http
GET <gateway>/v5/devices/password
```

Signed fields, in order:

```text
seq=1
userid=<userid>
uid=<camera uid>
pincode=Base64(HMAC-SHA1(key=UTF-8(uid), message=UTF-8(user-entered PIN)))
```

The API `hmac` covers all four fields above using the ordinary `token&token_secret` key. On success the app reads `data.password` and decrypts it using the same `uid.substring(0,16)` AES procedure. Error code `51125` is handled specially as a PIN/password failure.

The PIN is stored in a runtime `DeviceInfo` field after successful validation, but is not returned by `/v4/devices/list`.

## Requested connection/security-field matrix

| Requested concept | Proven source/result |
|---|---|
| UID | Top-level `uid`. |
| TUTK UID | For a type-0 list device, exactly the same top-level `uid`. |
| P2P UID | `DeviceInfo.e`, initialized to the same `uid`; copied to `P2PDevice.p2pid`. |
| Device UID | Same `uid` in this TUTK trace. |
| DID | Separate top-level `did`; not used for the native TUTK connect call. |
| Model | Top-level `model`, normalized by feature configuration. |
| `serverModel` | Not a response field consumed by this parser. In the APK's target asset, server model `6` maps to `yunyi.camera.y20`. |
| Firmware | **Not read from this endpoint.** Later device-info/pre-version IOCTRL calls provide version data. |
| IP/LAN address | `ipcParam.ip`; informational in this TUTK path, not passed to `IOTC_Connect_ByUID_Parallel`. |
| Online state | Top-level `online`; native session status later provides actual P2P/relay/LAN mode. |
| PIN code | **Not returned.** Only `hasPincode` is returned. |
| Password | Top-level encrypted `password`, or literal fallback `888888`; blanked until PIN lookup if protected. |
| Encrypted password | Top-level `password`, interpreted as hex AES ciphertext. |
| Device key | No TUTK device-key field is consumed from this response. `P2PDevice.tnpLicenseDeviceKey` is initialized empty on this list path and is for TNP. A later `GET_IPC_INFO` IOCTRL response can parse a JSON `key`, but that happens after connection and is not used to create this TUTK session. |
| Security key | For TUTK, the plaintext camera password drives AV authentication and the I-frame AES key. No distinct list security-key field is consumed. |
| Connection mode | Top-level `type` selects SDK family. P2P vs relay vs LAN is learned only after `IOTC_Session_Check_Ex`. |
| TUTK/Kalay server information | **No explicit server field is consumed for type 0.** Master/relay resolution is internal to `libIOTCAPIs.so`. |
| TNP server information | `P2PDevice.tnpServerString` and license key exist, but this `/v4/devices/list` parser initializes both empty. Other TNP-specific endpoints populate them. |

## Resulting `P2PDevice`

`DeviceInfo.c()` constructs:

```text
P2PDevice(
    uid                  = cloud uid,
    p2pid                = cloud uid,
    account              = "admin",      // blank input normalized by constructor
    pwd                  = decrypted/fallback password, or empty until PIN lookup,
    type                 = cloud type,
    tnpServerString      = "",
    tnpLicenseDeviceKey  = "",
    model                = normalized model,
    isEncrypted          = ipcParam.p2p_encrypt (default true),
    device2UtcOffsetHour = app-derived offset,
    tnpHeaderVersion     = 0,
    wakeup               = ipcParam.wakeup,
    forceRelay           = account/model-derived boolean
)
```

For `type == 0`, the TNP-only fields and `forceRelay` are not passed to the `TutkCamera` constructor. The exact native trace continues in [tutk-flow.md](tutk-flow.md).
