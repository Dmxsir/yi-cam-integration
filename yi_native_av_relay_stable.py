#!/usr/bin/env python3
"""Development adapter: run the proven native AV relay by camera stable_id.

The future Add-on will call the reusable camera/runtime core directly. This
small CLI exists only to prove Phase 6B without modifying production streams or
re-introducing camera-name/model whitelists.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import yi_camera_runtime
import yi_native_av_relay as relay


def main() -> int:
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--stable-id", required=True)
    selected, remaining = selector.parse_known_args()

    stable_id = selected.stable_id.strip()
    if not stable_id:
        raise SystemExit("--stable-id must not be empty")

    def fresh_stable_target(timeout: float) -> tuple[Any, dict[str, Any]]:
        material, descriptor = yi_camera_runtime.runtime_material_for(
            stable_id,
            timeout=timeout,
        )
        safe = descriptor.safe_dict()
        return material, {
            "selected_camera": descriptor.name,
            "stable_id": descriptor.stable_id,
            "raw_model": descriptor.raw_model,
            "normalized_model": descriptor.normalized_model,
            "p2p_type": 2,
            "cloud_online_reported": descriptor.cloud_online_reported,
            "p2p_encrypt": descriptor.encrypted,
            "wakeup": descriptor.wakeup,
            "profile_candidate": descriptor.profile_candidate,
            "evidence": "PHASE6_STABLE_ID_RUNTIME",
            "safe_descriptor": safe,
        }

    # Keep the proven relay/mux/worker unchanged. Only replace its Phase 3
    # name/model-specific material resolver with the generic stable-id provider.
    original_resolver = relay.phase3e._fresh_exact_target
    original_argv = sys.argv
    try:
        relay.phase3e._fresh_exact_target = fresh_stable_target
        sys.argv = [original_argv[0], *remaining]
        return relay.main()
    finally:
        relay.phase3e._fresh_exact_target = original_resolver
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
