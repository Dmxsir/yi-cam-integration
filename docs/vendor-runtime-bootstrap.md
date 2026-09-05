# Local YI vendor runtime bootstrap

The App does not package or download `libPPPP_API.so`. Supply an official YI
Home artifact locally before starting the App:

- preferred: `/share/yi_rtsp/yi-home.apk`
- advanced: `/share/yi_rtsp/libPPPP_API.so`

At startup the App prefers the APK, locates its ARM64 library, validates that
the input is an AArch64 ELF shared object, and atomically installs it as
`/data/vendor/libPPPP_API.so` with restrictive permissions. It logs only the
source type, size, and SHA-256 for local diagnostics. The source artifact and
binary contents are never logged or copied into the Docker build context.

Later starts reuse the valid file under `/data/vendor/` without reading the
source again. Runtime-only symlinks expose it at the two already-proven Bionic
guest paths, so PPPP/TNP, media, retry, RTSP, Frigate, and cloud-session
behavior remain unchanged.

If no valid installed library or local artifact is available, startup stops
with an instruction to place the official APK in `/share/yi_rtsp/`.
