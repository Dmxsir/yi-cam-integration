from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import prepare_ha_app_context as prepare


def _runtime(root: Path) -> Path:
    runtime = root / "runtime"
    files = {
        "system/bin/linker64": b"linker",
        "system/lib64/libc.so": b"libc",
        "system/lib64/libdl.so": b"libdl",
        "data/local/tmp/yi-phase3g/android_pppp_av_stream": b"media-worker",
        "data/local/tmp/yi-phase3g/libPPPP_API.so": b"vendor-media",
        "data/local/tmp/yi-online-status/android_pppp_online_probe": b"online-worker",
        "data/local/tmp/yi-online-status/libPPPP_API.so": b"vendor-online",
        "vendor-copy/nested/LIBpppp_api.SO": b"vendor-extra",
        "vendor-copy/yi-home.apk": b"vendor-apk",
    }
    for name, payload in files.items():
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return runtime


class PrepareHaAppContextTests(unittest.TestCase):
    def test_prepared_docker_context_contains_no_vendor_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / "yi_home"
            (app / "rootfs").mkdir(parents=True)
            (app / "rootfs/.gitkeep").touch()

            manifest_path, _ = prepare.prepare_context(_runtime(root), app)

            self.assertEqual(list(prepare.iter_vendor_libraries(app)), [])
            self.assertEqual(list(prepare.iter_vendor_artifacts(app)), [])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["vendor_library_packaged"])
            self.assertNotIn("online_pppp_library", manifest["critical_artifacts"])

    def test_hard_guard_rejects_library_anywhere_in_build_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "yi_home"
            leaked = app / "outside-rootfs" / prepare.VENDOR_LIBRARY_NAME
            leaked.parent.mkdir(parents=True)
            leaked.write_bytes(b"must fail")

            with self.assertRaisesRegex(SystemExit, "Docker build context"):
                prepare.prepare_context(_runtime(Path(temporary)), app)


if __name__ == "__main__":
    unittest.main()
