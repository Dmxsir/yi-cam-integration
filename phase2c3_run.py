"""Phase 2C.3 entry point: run the controlled retry against POOL only."""

from __future__ import annotations

import yi_tnp_oracle as oracle


def main(argv: list[str] | None = None) -> int:
    # fresh_cloud_preflight() uses APPROVED_TARGETS[0] and [1]. Repeating POOL
    # deliberately disables automatic fallback to another camera for this
    # single-variable experiment.
    oracle.APPROVED_TARGETS = ("POOL", "POOL")
    return oracle.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
