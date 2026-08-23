# YI Home

Experimental Home Assistant App packaging for the native YI Home PPPP/TNP camera engine.

Current Phase 6D target is `amd64` only. The App owns cloud discovery, per-camera runtime lifecycle, authoritative PPPP online/offline status, persistent desired-running policy and managed RTSP publication.

The App backend is internal to the Home Assistant App network. RTSP is exposed on TCP 8554 for optional consumers such as Frigate. YI account setup will be handed from the Home Assistant Integration to the authenticated internal API in Phase 6D.2/6E; it is not an App option.

For development build preparation see `DOCS.md`.
