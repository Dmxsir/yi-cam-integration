#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

bash "$ROOT/tools/phase3_pppp_probe/cleanup_phase6c_reprobe_dev.sh"
exec bash "$ROOT/tools/phase3_pppp_probe/run_phase6c_reprobe_smoke.sh"
