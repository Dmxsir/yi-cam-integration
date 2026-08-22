#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROD_ROOT="${PROD_ROOT:-$HOME/Documents/yi-cam-integration}"
PYTHON="${PYTHON:-$PROD_ROOT/.venv/bin/python}"
ENV_FILE="${ENV_FILE:-$PROD_ROOT/.env.local}"

fail() { echo "ERROR: $*" >&2; exit 1; }

[[ -x "$PYTHON" ]] || fail "python missing: $PYTHON"
[[ -f "$ENV_FILE" ]] || fail "env file missing: $ENV_FILE"

"$PYTHON" -m py_compile "$ROOT/yi_camera_manager.py" "$ROOT/yi_cloud_probe.py"
echo "python_compile=PASS"
echo "production_modified=false"

"$PYTHON" - "$ROOT" "$ENV_FILE" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
env_file = Path(sys.argv[2])
sys.path.insert(0, str(root))

import yi_camera_manager as cameras
import yi_tnp_oracle as oracle

oracle.load_env_file(env_file)
manager = cameras.YiCameraManager(timeout=10.0)
try:
    manager.login_and_list()
    rows = []
    for stable_id, raw in manager._cameras.items():
        state = raw.get("state")
        online = raw.get("online")
        last_access = raw.get("lastAccessTime")
        p2p_type = raw.get("type")
        rows.append(
            {
                "name": str(raw.get("name", "")),
                "stable_id": stable_id,
                "online": online if isinstance(online, (bool, int, str)) else None,
                "online_type": type(online).__name__,
                "state": state if isinstance(state, (bool, int, str)) else None,
                "state_type": type(state).__name__,
                "lastAccessTime": last_access if isinstance(last_access, (int, float, str)) else None,
                "type": p2p_type if isinstance(p2p_type, (int, str)) else None,
            }
        )
    rows.sort(key=lambda item: (item["name"].casefold(), item["stable_id"]))
    print(json.dumps({"ok": True, "camera_count": len(rows), "cameras": rows, "secrets_exposed": False}, ensure_ascii=False, indent=2))
    print("PHASE6_CLOUD_STATUS_PROBE=PASS")
finally:
    manager.close()
PY