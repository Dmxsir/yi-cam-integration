#!/usr/bin/env python3
"""Phase 5 camera-selecting wrapper around the proven native YI AV relay.

The underlying relay and Phase 3 transport remain unchanged. This wrapper only
selects the exact cloud camera name before delegating to yi_native_av_relay.
For the first multi-camera proof it is intentionally restricted to raw model 83
cameras already known from the account inventory.
"""

from __future__ import annotations

import argparse
import sys

import yi_native_av_relay as relay


ALLOWED_CAMERAS = ("מחסן", "pool")


def main() -> int:
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--camera", default="מחסן")
    selected, remaining = selector.parse_known_args()

    if selected.camera not in ALLOWED_CAMERAS:
        allowed = ", ".join(repr(name) for name in ALLOWED_CAMERAS)
        raise SystemExit(
            f"Phase 5 model-83 proof only allows --camera one of: {allowed}"
        )

    # run_phase3e_tnp._fresh_exact_target reads TARGET at call time. Changing
    # only this module-level selector preserves every other proven Phase 3
    # guard, including raw model 83 / type 2 validation and the native worker.
    relay.phase3e.TARGET = selected.camera

    original_argv = sys.argv
    try:
        sys.argv = [original_argv[0], *remaining]
        return relay.main()
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    raise SystemExit(main())
