# IOCTRL map for live video and adjacent features

Constants come from `com.tutk.IOTC.AVIOCTRLDEFs` unless noted. “Used” means a call site was found in the decompiled APK; declaration alone is not treated as proof of an active feature. TUTK commands use little-endian fields because `AntsCamera.isByteOrderBig()` is false for type 0.

## Live video and playback

| Name | Dec | Hex | Payload / behavior | Evidence |
|---|---:|---:|---|---|
| `IOTYPE_USER_IPCAM_START` | 511 | `0x01FF` | 4-byte little-endian use counter; starts unencrypted live video. | `AntsCameraTutk.doGoLive()` |
| `IOTYPE_USER_IPCAM_START_RESP` | 512 | `0x0200` | Named response for legacy start. | Declared; live start does not register a response callback. |
| `IOTYPE_USER_IPCAM_START2` | 8190 | `0x1FFE` | Same 4-byte use-counter payload; selected when `p2p_encrypt` is true. | `AntsCameraTutk.doGoLive()` |
| `IOTYPE_USER_IPCAM_STOP` | 767 | `0x02FF` | Eight zero bytes; stops live display. | `TutkCamera.stopShow()` |
| `IOTYPE_USER_IPCAM_RECORD_PLAYCONTROL` | 794 | `0x031A` | `SMsgAVIoctrlPlayRecord`; start/seek/stop recorded playback. | TUTK playback code |
| `IOTYPE_USER_IPCAM_RECORD_PLAYCONTROL_RESP` | 795 | `0x031B` | Record-play response. | Response handler |
| `IOTYPE_USER_IPCAM_RECORD_PLAYCONTROL2` | 12718 | `0x31AE` | Encrypted-session variant of playback control. | TUTK encrypted playback/stop |
| local `IOTYPE_USER_IPCAM_I_FRAME_REQ` | 916 | `0x0394` | A serializer for channel 0 exists. | Private constant/helper in `TutkCamera`; no send call found. |
| local `IOTYPE_USER_IPCAM_I_FRAME_RESP` | 917 | `0x0395` | Paired response. | Declared only. |
| `IOTYPE_USER_IPCAM_IFRAME_PIECES_REQ` | 4633 | `0x1219` | Name suggests I-frame fragment request. | Declared only in the scoped search. |

The required phase-1 command is `START2` for an encrypted Y20 and `START` otherwise. It is sent only after an AV index has been established through `avClientStart2`.

## Session setup and authentication

The core TUTK authentication operation is **not an IOCTRL**. It is:

```text
IOTC_Get_SessionID()
IOTC_Connect_ByUID_Parallel(uid, sid)
avClientStart2(sid, userOrNonce, passwordOrDerivedPassword, timeout, ..., channel=0, ...)
```

| Name | Dec | Hex | Payload / behavior | Target relevance |
|---|---:|---:|---|---|
| `IOTYPE_UPDATE_NONCE_REQ` | 65280 | `0xFF00` | Eight zero bytes in `CameraCommandHelper.updateNonce()`. | Active caller found for `AntsCameraTnp`; no TUTK/Y20 connect caller found. |
| `IOTYPE_USER_IPCAM_START_CHECK` | 4887 | `0x1317` | Eight zero bytes. | `CameraCommandHelper.restartCheckDevice()`; adjacent health/session check. |
| `IOTYPE_USER_IPCAM_START_CHECK_RESP` | 4888 | `0x1318` | Response. | Declared and paired. |
| `IOTYPE_USER_IPCAM_CHECK_STAT_REQ` | 4889 | `0x1319` | Check status request. | Declared. |
| `IOTYPE_USER_IPCAM_CHECK_STAT_REQ_RESP` | 4890 | `0x131A` | Check status response. | Declared. |
| `IOTYPE_USER_IPCAM_HEART` | 110 | `0x006E` | Heartbeat command. | Declared; not part of the proven live-start sequence. |

Encrypted TUTK AV authentication and its HMAC are documented in [tutk-flow.md](tutk-flow.md).

## Device information and synchronization

| Name | Dec | Hex | Payload / response |
|---|---:|---:|---|
| `IOTYPE_USER_IPCAM_DEVINFO_REQ` | 816 | `0x0330` | `SMsgAVIoctrlDeviceInfoReq.parseContent()`; sent by `CameraCommandHelper.getDeviceInfo`. |
| `IOTYPE_USER_IPCAM_DEVINFO_RESP` | 817 | `0x0331` | `SMsgAVIoctrlDeviceInfoResp`; includes firmware/hardware/interface/version fields. |
| `IOTYPE_USER_IPCAM_GET_PRE_VERSION` | 4931 | `0x1343` | Pre-version request. |
| `IOTYPE_USER_IPCAM_GET_PRE_VERSION_RESP` | 4932 | `0x1344` | Pre-version response. |
| `IOTYPE_USER_IPCAM_GET_IPC_INFO` | 4939 | `0x134B` | IPC information request. |
| `IOTYPE_USER_IPCAM_GET_IPC_INFO_RESP` | 4940 | `0x134C` | IPC information response. |
| `IOTYPE_USER_IPCAM_GET_REALTIME_STATE` | 4989 | `0x137D` | Realtime state request. |
| `IOTYPE_USER_IPCAM_GET_REALTIME_STATE_RESP` | 4990 | `0x137E` | Realtime state response. |
| `IOTYPE_USER_IPCAM_TRIGGER_SYNC_INFO_FROM_SERVER_REQ` | 960 | `0x03C0` | 4-byte little-endian integer reason/mode. Observed values include 0, 1, and 2 in different UI flows. |
| `IOTYPE_USER_IPCAM_TRIGGER_SYNC_INFO_FROM_SERVER_RESP` | 961 | `0x03C1` | First 4 response bytes parsed as an integer. |

The synchronization command is used after settings/state changes; it is not necessary to construct the initial TUTK session.

## Stream quality and encoding

| Request | Dec | Response | Dec | Payload builder |
|---|---:|---|---:|---|
| `IOTYPE_USER_IPCAM_SET_RESOLUTION` | 4881 | `..._RESP` | 4882 | `SMsAVIoctrlResolutionCfg.parseContent(value, littleEndian)` |
| `IOTYPE_USER_IPCAM_GET_RESOLUTION` | 4883 | `..._RESP` | 4884 | eight zero bytes |
| `IOTYPE_USER_IPCAM_SET_HD_RESOLUTION` | 4905 | `..._RESP` | 4906 | `SMsAVIoctrlHDResolutionCfg.parseContent(value, littleEndian)` |
| `IOTYPE_USER_IPCAM_SET_ENCODING_FORMAT_REQ` | 9040 | `..._RESP` | 9041 | `SMsAVIoctrlSetEncodeTypeResp.parseContent(value, littleEndian)` |
| `IOTYPE_USER_IPCAM_SET_HIGH_RESOLUTION_REQ` | 9042 | `..._RESP` | 9043 | `SMsAVIoctrlSetHighResolutionResp.parseContent(value, littleEndian)` |

The method names for the last two payload classes say `Resp` despite being used to build requests; the table preserves the APK names. The live-start path does not issue a quality command automatically in `doGoLive()`. Quality is controlled by separate UI/command-helper calls.

## Audio and speaker

| Name | Dec | Hex | Payload / behavior |
|---|---:|---:|---|
| `IOTYPE_USER_IPCAM_AUDIOSTART` | 768 | `0x0300` | Eight zero bytes; begins camera-to-client audio, then `avRecvAudioData` worker starts. |
| `IOTYPE_USER_IPCAM_AUDIOSTOP` | 769 | `0x0301` | Eight zero bytes; stops listening. |
| `IOTYPE_USER_IPCAM_SPEAKERSTART` | 848 | `0x0350` | 4-byte little-endian talk mode for ordinary TUTK speaking. Y20 chooses AAC/AEC recording classes. |
| `IOTYPE_USER_IPCAM_SPEAKERSTOP` | 849 | `0x0351` | Declared and actively sent by TNP code. `TutkCamera.stopSpeaking()` stops its worker but does not send this constant in the examined method. |
| `IOTYPE_USER_IPCAM_SET_MIC_VOLUME` | 4923 | `0x133B` | Microphone volume request. |
| `IOTYPE_USER_IPCAM_SET_MIC_VOLUME_RESP` | 4924 | `0x133C` | Response. |
| `IOTYPE_USER_IPCAM_SET_SPEAKER_VOLUME` | 4915 | `0x1333` | Speaker volume request. |
| `IOTYPE_USER_IPCAM_SET_SPEAKER_VOLUME_RESP` | 4916 | `0x1334` | Response. |
| `IOTYPE_USER_IPCM_SET_AUDIO_MODE` | 20481 | `0x5001` | Audio mode request. |
| `IOTYPE_USER_IPCM_SET_AUDIO_MODE_RESP` | 20482 | `0x5002` | Response. |

Audio is optional for the requested H.264 bridge and is not required to reach `avRecvFrameData2`.

## Encryption-related behavior

There is no separate TUTK “enable video encryption” IOCTRL in the traced Y20 path. Cloud `ipcParam.p2p_encrypt` selects all of the following before/at stream start:

- nonce/HMAC arguments to `avClientStart2`;
- `START2` (`8190`) instead of `START` (`511`);
- `RECORD_PLAYCONTROL2` instead of `RECORD_PLAYCONTROL`;
- AES decryption of two blocks in each received I-frame.

`IOTC_Set_Partial_Encryption` is exported by `libIOTCAPIs.so` and has a JNI wrapper declaration, but no invocation was found in `TutkCamera`; it is not part of the proven Java Y20 sequence.

## RTMP commands

These commands are implemented by `CameraCommandHelper`, but the scoped search found no app-layer call to the four helper methods in this APK. They are documented because they are packaged behavior, not because the normal Y20 player uses RTMP.

| Request | Dec | Response | Dec | Exact helper payload |
|---|---:|---|---:|---|
| `IOTYPE_USER_IPCAM_START_RTMP_REQ` | 944 | `..._RESP` | 945 | 4-byte little-endian integer via `SMsgAVIoctrlStartRtmpReq.parseContent`. |
| `IOTYPE_USER_IPCAM_STOP_RTMP_REQ` | 946 | `..._REQ_RESP` | 947 | eight zero bytes. |
| `IOTYPE_USER_IPCAM_QUERY_RTMP_STAT_REQ` | 948 | `..._RESP` | 949 | eight zero bytes. |
| `IOTYPE_USER_IPCAM_SET_RTMP_ADDR_REQ` | 950 | `..._RESP` | 951 | raw `String.getBytes()` output; no explicit terminator or fixed-size padding in the helper. |

The app's response parser for these commands expects at least 516 bytes: a 4-byte little-endian `leftTime` followed by a 512-byte URL region converted to a string and trimmed.

The names requested as `IOTYPE_USER_IPCAM_STOP_RTMP` and similar do not occur exactly; the APK names are `IOTYPE_USER_IPCAM_STOP_RTMP_REQ` and `IOTYPE_USER_IPCAM_STOP_RTMP_REQ_RESP`.

## Minimum command set for the future bridge

For video-only live viewing after a successful native AV channel:

1. send `START2`/8190 for `p2p_encrypt == true`, otherwise `START`/511;
2. receive compressed frames with `avRecvFrameData2`;
3. decrypt the two protected I-frame blocks only in encrypted mode;
4. on shutdown, send `STOP`/767 and close the AV/IOTC session.

Quality, audio, synchronization, RTMP, and playback commands are not prerequisites for this minimal chain.
