#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
ERROR: this temporary SSH handoff path is intentionally retired.
Home Assistant Supervisor protects GET /discovery with a Home-Assistant-Core-only check,
so Terminal & SSH must not retrieve the YI Home App bearer token.

Use the YI Home custom integration (async_step_hassio) for the authenticated
Integration -> App credential handoff.
EOF
exit 2
