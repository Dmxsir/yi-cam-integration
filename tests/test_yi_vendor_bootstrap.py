from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yi_vendor_bootstrap as bootstrap


def _elf(*, machine: int = bootstrap.AARCH64_MACHINE, marker: bytes = b"") -> bytes:
    ident = bytearray(16)
    ident[:4] = b"\x7fELF"
    ident[4:7] = bytes((2, 1, 1))
    size = 8192
    header = struct.pack(
        "<16sHHIQQQIHHHHHH",
        bytes(ident),
        3,
        machine,
        1,
        0,
        64,
        0,
        0,
        64,
        56,
        1,
        64,
        0,
        0,
    )
    program_header = struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, size, size, 4096)
    return (header + program_header).ljust(size - len(marker), b"\0") + marker


class VendorRuntimeBootstrapTests(unittest.TestCase):
    def test_valid_direct_library_import(self) -> None:
        payload = _elf(marker=b"direct")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = root / "share"
            share.mkdir()
            (share / bootstrap.LIBRARY_NAME).write_bytes(payload)

            result = bootstrap.bootstrap_vendor_runtime(root / "data", share)

            self.assertFalse(result.reused)
            self.assertEqual(result.source, "direct_library")
            self.assertEqual(result.path.read_bytes(), payload)
            self.assertEqual(result.sha256, hashlib.sha256(payload).hexdigest())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(result.path.stat().st_mode), 0o600)

    def test_valid_apk_extraction_prefers_standard_arm64_path(self) -> None:
        preferred = _elf(marker=b"preferred")
        fallback = _elf(marker=b"fallback")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = root / "share"
            share.mkdir()
            with zipfile.ZipFile(share / bootstrap.APK_NAME, "w") as archive:
                archive.writestr(
                    f"assets/native/arm64-v8a/{bootstrap.LIBRARY_NAME}", fallback
                )
                archive.writestr(f"lib/arm64-v8a/{bootstrap.LIBRARY_NAME}", preferred)
                archive.writestr(f"lib/armeabi-v7a/{bootstrap.LIBRARY_NAME}", b"ignored")

            result = bootstrap.bootstrap_vendor_runtime(root / "data", share)

            self.assertEqual(result.source, "official_apk")
            self.assertEqual(result.path.read_bytes(), preferred)

    def test_wrong_architecture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = root / "share"
            share.mkdir()
            (share / bootstrap.LIBRARY_NAME).write_bytes(_elf(machine=62))

            with self.assertRaisesRegex(bootstrap.VendorRuntimeError, "AArch64"):
                bootstrap.bootstrap_vendor_runtime(root / "data", share)

            self.assertFalse((root / "data/vendor" / bootstrap.LIBRARY_NAME).exists())

    def test_malformed_non_elf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = root / "share"
            share.mkdir()
            (share / bootstrap.LIBRARY_NAME).write_bytes(b"not an ELF".ljust(8192, b"x"))

            with self.assertRaisesRegex(bootstrap.VendorRuntimeError, "not an ELF"):
                bootstrap.bootstrap_vendor_runtime(root / "data", share)

    def test_truncated_elf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / bootstrap.LIBRARY_NAME
            path.write_bytes(b"\x7fELF" + b"\0" * 60)

            with self.assertRaisesRegex(bootstrap.VendorRuntimeError, "truncated"):
                bootstrap.validate_vendor_library(path)

    def test_existing_private_library_is_reused_without_import(self) -> None:
        installed = _elf(marker=b"installed")
        supplied = _elf(marker=b"new-source")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "data/vendor" / bootstrap.LIBRARY_NAME
            target.parent.mkdir(parents=True)
            target.write_bytes(installed)
            share = root / "share"
            share.mkdir()
            (share / bootstrap.LIBRARY_NAME).write_bytes(supplied)

            result = bootstrap.bootstrap_vendor_runtime(root / "data", share)

            self.assertTrue(result.reused)
            self.assertEqual(result.source, "private_data")
            self.assertEqual(target.read_bytes(), installed)

    def test_missing_runtime_fails_with_short_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = root / "share/yi_rtsp"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = bootstrap.main(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--share-dir",
                        str(share),
                        "--runtime-root",
                        str(root / "runtime"),
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn(str(share / bootstrap.APK_NAME), stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_install_replaces_only_after_valid_temp_file_is_complete(self) -> None:
        payload = _elf(marker=b"atomic")
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "vendor" / bootstrap.LIBRARY_NAME
            target.parent.mkdir()
            target.write_bytes(b"old")
            real_replace = os.replace
            observed_old_target: list[bool] = []

            def replace(source: Path, destination: Path) -> None:
                observed_old_target.append(Path(destination).read_bytes() == b"old")
                real_replace(source, destination)

            with patch.object(bootstrap.os, "replace", side_effect=replace) as mocked:
                bootstrap.persist_vendor_library(io.BytesIO(payload), target)

            mocked.assert_called_once()
            self.assertEqual(observed_old_target, [True])
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_runtime_compatibility_uses_symlinks_not_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vendor = root / "data/vendor" / bootstrap.LIBRARY_NAME
            vendor.parent.mkdir(parents=True)
            vendor.write_bytes(_elf())
            runtime = root / "runtime"
            for guest_dir in bootstrap.COMPATIBILITY_GUEST_DIRS:
                (runtime / guest_dir).mkdir(parents=True)

            with patch.object(bootstrap.os, "symlink") as symlink:
                bootstrap.install_compatibility_links(vendor, runtime)

            self.assertEqual(symlink.call_count, 2)
            for call in symlink.call_args_list:
                self.assertEqual(call.args[0], vendor)

    def test_diagnostics_do_not_expose_bytes_or_mutate_environment_or_argv(self) -> None:
        secret = b"DO_NOT_EXPOSE_VENDOR_CONTENT"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = root / "share"
            share.mkdir()
            (share / bootstrap.LIBRARY_NAME).write_bytes(_elf(marker=secret))
            argv = [
                "--data-dir",
                str(root / "data"),
                "--share-dir",
                str(share),
                "--runtime-root",
                str(root / "runtime"),
            ]
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                patch.dict(os.environ, {"SAFE_MARKER": "unchanged"}, clear=True),
                patch.object(bootstrap, "install_compatibility_links"),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                before = dict(os.environ)
                rc = bootstrap.main(argv)
                after = dict(os.environ)

            combined = stdout.getvalue() + stderr.getvalue() + " ".join(argv)
            self.assertEqual(rc, 0)
            self.assertEqual(before, after)
            self.assertNotIn(secret.decode(), combined)
            self.assertIn("proprietary_bytes_exposed=false", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
