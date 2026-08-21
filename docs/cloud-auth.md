# YI cloud authentication

This document describes the behavior in APK version `5.6.5_20220819031350`. It does not claim that the live service still accepts the same contract.

## Region and host selection

`com.ants360.yicamera.b.d` loads `assets/locale.json`. Each entry has a two-letter country `code`, a `server` (`USA`, `EU`, or `SEA` in the international asset), a phone code, and display names. It reads `LoginSelectedCountry`; when empty, it stores and tries the Android locale country. If no asset entry matches, it uses the first asset entry (Albania/EU in this APK). It then chooses the server as follows:

```text
if ManualChangeServer == false and saved LoginServer is non-empty:
    region = saved LoginServer
else:
    region = selected LocaleInfo.server
```

The explicit region setter updates `LoginServer`. Selecting a country through the country path updates both the selected country and its asset-defined server.

For example, the asset maps `US -> USA`, `IL -> EU`, `AU -> SEA`, and `TW -> SEA`. China-specific code uses the internal region value `CHN`.

The current request path is routed by `com.ants360.yicamera.c.c.a(path)`:

| Internal region | Host |
|---|---|
| `CHN` | `https://api.xiaoyi.com` |
| `USA` | `https://gw-us.xiaoyi.com` |
| `EU` | `https://gw-eu.xiaoyi.com` |
| other / `SEA` | `https://gw-sg.xiaoyi.com` |

The APK also contains an older/direct host mapper in `com.ants360.yicamera.e.a.c.b(path)`:

| Internal region | Direct host |
|---|---|
| `CHN` | `https://api.xiaoyi.com` |
| `USA` | `https://api.us.xiaoyi.com` |
| `EU` | `https://api.eu.xiaoyi.com` |
| other / `SEA` | `https://api.xiaoyi.com.tw` |

The three phase-1 endpoints studied here use the first, gateway-based router. Region is selected before login; it is not discovered from a successful login response.

## Shared explicit headers

`com.ants360.yicamera.e.a.b.a` adds the following to GET, POST, PUT, PATCH, and DELETE requests:

```http
x-kamihome-appType: ANDROID
x-kamihome-packageType: RELEASE
User-Agent: yihome/5.6.5_20220819031350 (<Build.MODEL>; Android <Build.VERSION.RELEASE><optional MIUI marker>; <app locale>)
x-xiaoyi-appCountryCode: <selected two-letter country code>
x-xiaoyi-appVersion: android;319;5.6.5_20220819031350
```

The locale portion is normalized by `b.d.n()` to one of the app-supported forms such as `en-US`, `fr-FR`, `de-DE`, `es-ES`, `it-IT`, `ja-JP`, `ko-KR`, `zh-CN`, or `zh-TW`; unsupported locales fall back to `en-US`.

No `Authorization` header, cookie, Android ID, advertising ID, IMEI, install ID, or device-generated UUID is explicitly added by this request layer. OkHttp may add ordinary transport headers such as `Host`, `Connection`, or `Accept-Encoding`; those are library behavior rather than app-defined authentication inputs.

The bundled OkHttp client uses a permissive hostname verifier and a custom permissive trust manager. The prototype intentionally does **not** copy that unsafe TLS behavior.

## `/v4/users/login`

### Call chain

Two app paths build the same parameter set:

- `base.ad.a(account,password,callback)` -> static reactive builder `e.a.d.c(...)`.
- `base.ad.b(account,password,callback)` -> legacy facade `e.g.k(...)`.

Both ultimately create the GET request with `e.a.b.a.a(url, params)`.

### Exact request

| Property | Value |
|---|---|
| Method | `GET` |
| URL | `<regional gateway>/v4/users/login` |
| Query | Described below |
| Body | none |
| Content-Type | none set; GET has no request body |
| Timestamp | none |
| Nonce | none |
| API HMAC/signature | none |

Parameters are inserted in this order before being copied to the request parameter container:

1. `seq=1`
2. Account field:
   - non-China: `account=<user input>`
   - China and input matches the app email regex: `email=<user input>`
   - China otherwise: `mobile=<user input>`
3. `password=<transformed password>`
4. `dev_name=<Build.BRAND>`
5. `dev_type=<Build.MODEL>`
6. `dev_os_version=Android <Build.VERSION.RELEASE>`

The email regex is `[A-Z0-9a-z._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,4}` applied as a full match.

Although the source parameters originate in a `LinkedHashMap`, `e.a.b.b` copies them into a `ConcurrentHashMap`; query serialization order is therefore not a reliable part of the wire contract. Parameter names and values are proven. OkHttp `HttpUrl.Builder.query(...)` performs final URL canonicalization.

### Password transformation

`com.ants360.yicamera.util.aa` performs:

```text
password_parameter = Base64(
    HMAC-SHA256(
        key = UTF-8("KXLiUdAsO81ycDyEJAeETC$KklXdz3AC"),
        message = raw password bytes
    )
)
```

Android Base64 flag `NO_WRAP` is used. Standard Base64 alphabet and `=` padding remain present. Android's default charset is UTF-8 in practice; the code does not explicitly name a charset for the password message bytes.

The APK does **not** MD5 or SHA-hash the password before this HMAC, and it does not add the account, timestamp, or nonce to this transform.

### Response consumed by the app

The normal login handler first checks top-level `code == 20000`, then reads `data` as an object. A response sufficient for every field consumed by this path has this shape:

```json
{
  "code": 20000,
  "data": {
    "userid": "string",
    "account": "string",
    "name": "string",
    "img": "string",
    "userMobileRegion": "string",
    "mobile": "string",
    "token": "string",
    "token_secret": "string",
    "birthday": "string",
    "first_name": "string",
    "last_name": "string",
    "register_time": 0,
    "openId": "string",
    "flag": false
  }
}
```

This is a consumed-field schema, not a claim that all fields are required or that the server cannot return more. `flag` is returned to the login UI. In one normal legacy parser `email` is read instead of `account`. Social-login paths additionally consume `auth_email` and `auth_id`; those are not part of the password-login request.

### Confirmed EU production response (2026)

A controlled Phase 2A validation against `https://gw-eu.xiaoyi.com/v4/users/login` confirmed HTTP 200 with a JSON object response. Current production differs from the APK-derived example in these types:

- top-level `code` is the JSON string `"20000"`;
- `data.userid` is a JSON number;
- `data.register_time` is a JSON string;
- `data.token` and `data.token_secret` remain present as strings.

The probe accepts only an integer response code or a canonical decimal response-code string, normalizes it to an integer, and still requires normalized code `20000`. It accepts `userid` as a non-empty JSON string or JSON integer and converts it to a string before signing later requests. `register_time` is not needed for authentication or P2P discovery and is not type-validated. Response `Content-Type` is treated as representation metadata: HTTP 200 UTF-8 content that parses as JSON and passes the required YI schema validation is accepted even if the server labels it `text/html; charset=utf-8`.

No production account identifier, token, token secret, or other response value is recorded here.

Persistence/mapping in `bean.ab` is:

| Response | App meaning / preference key |
|---|---|
| `userid` | User ID / `USER_NAME` |
| `token` | User token / `TOKEN` |
| `token_secret` | User token secret / `TOKEN_SECRET` |
| `account` or `email` | Account label |
| `openId` | Open ID |

For later cloud signing, the effective key string is exactly `token + "&" + token_secret`.

The normal login parser does **not** read `userToken` or `userTokenSecret` literal JSON fields. Those conceptual names correspond to the values read from `token` and `token_secret` here.

The following requested login-response facts are **UNKNOWN/not consumed by this implementation**:

- refresh token;
- normal-login auth token distinct from `token`;
- token expiration time;
- region/server returned by login.

Social-provider request code contains provider-side `reftoken` and `expires` inputs, but that is a different flow and is not evidence of a YI password-login refresh token.

## Cloud HMAC used after login

For signed API calls, `e.d.a(LinkedHashMap,key)` constructs the canonical string by iterating insertion order and joining literal, unescaped pairs:

```text
key1=value1&key2=value2&...
```

It then computes:

```text
hmac = Base64(HMAC-SHA1(
    key = UTF-8(token + "&" + token_secret),
    message = UTF-8(canonical_string)
))
```

Canonicalization happens before URL encoding. The generated `hmac` is added as another query parameter.

The observed `HmacSha1.EnResult(...)` string is in the APK's generic `com.xiaoyi.base.http.i` signer, used by additional model/body classes. The three phase-1 endpoints above use `util.q`/`e.d` directly. Both implementations are standard Base64 HMAC-SHA1, but their parameter containers differ; this analysis follows the actual caller for each endpoint.

## `/v4/users/auth_token`

### Purpose and caller

This endpoint is **not a token refresh endpoint in the examined APK**. `DeviceShareQRCodeScanActivity` can route a scanned value to `UserScanLoginActivity`. When the logged-in user confirms, that activity calls `e.g.n(currentUserid, scannedToken, callback)`. The app treats top-level `code == 20000` as success and ignores response `data`.

The observed purpose is to authorize a scanned QR login/session using an already logged-in YI account.

### Exact request

| Property | Value |
|---|---|
| Method | `PUT` |
| URL | `<regional gateway>/v4/users/auth_token` |
| Query | `seq`, `userid`, scanned `token`, `hmac`, `country`, `appName` |
| Body | empty OkHttp `FormBody` |
| Content-Type | `application/x-www-form-urlencoded` (empty form body) |

Signing is intentionally performed before the last two parameters are added:

```text
canonical = "seq=1&userid=<current userid>&token=<scanned QR token>"
hmac = Base64(HMAC-SHA1(token + "&" + token_secret, canonical))
```

Final query fields are:

```text
seq=1
userid=<current userid>
token=<scanned QR token>
hmac=<signature above>
country=<selected country code>
appName=yihome
```

`country` and `appName` are therefore **not** covered by this HMAC.

### Response

Only top-level `code` is inspected. A response body beyond that, token lifetime, and the semantics of the scanned token are **UNKNOWN** from this call site.

## Prototype usage

The repository's `yi_cloud_probe` implements only password login and device listing. `discover` performs both calls in one process, keeps the returned token and token secret only in memory, and emits a purpose-built sanitized camera summary. The legacy `cameras` command is an alias for `discover`; neither command emits a raw API response. There is no option that reveals tokens, encrypted or decrypted camera passwords, PINs, DIDs, or MAC addresses.

After `python -m pip install -e .`, an explicit Israel/EU example is:

```powershell
$env:YI_ACCOUNT = "account@example.com"
yi_cloud_probe discover --region eu --country IL --device-brand samsung --device-model SM-S901B --android-version 13 --language en-US
```

The command securely prompts for the password because `YI_PASSWORD` is absent. `YI_PASSWORD` is also accepted for controlled non-interactive use. The device values above are illustrative; replace them with metadata intentionally chosen for the probe. The APK does not prove that arbitrary invented device metadata is acceptable, so the CLI does not silently invent it. Environment variables `YI_COUNTRY`, `YI_DEVICE_BRAND`, `YI_DEVICE_MODEL`, `YI_ANDROID_VERSION`, and `YI_LANGUAGE` can replace the corresponding options. Do not put credentials in tracked files.

`--show-uid` reveals the complete camera UID but leaves DID and MAC redacted. `--save-report <new-path>` writes exactly the sanitized report shown on stdout and refuses to overwrite an existing file. No report is created unless this option is supplied.

For a controlled schema failure, `login --debug-response-shape` adds only response headers relevant to representation, raw-body length/SHA-256, decoding/parsing outcomes, top-level key/type information, and wrapper shapes. It never includes body values, cookies, authorization headers, or the request URL/query. JSON strings are parsed a second time for shape only; gzip/Brotli bodies are observed but never blindly decompressed.
