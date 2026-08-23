#!/usr/bin/env python3
"""Stage the proven Phase 6 runtime into the Home Assistant App build context.

The Home Assistant App folder is its Docker build context, so development-only
artifacts under .analysis cannot be referenced directly by the Dockerfile. This
preparer copies only project Python sources and the already-proven Bionic/native
runtime into yi_home/rootfs. It intentionally never copies .env files, account
credentials or other home-directory configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = ROOT / ".analysis" / "phase3" / "bionic-root"
DEFAULT_APP_DIR = ROOT / "yi_home"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def reset_rootfs(rootfs: Path) -> None:
    rootfs.mkdir(parents=True, exist_ok=True)
    for child in rootfs.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def copy_project_sources(destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source in sorted(ROOT.glob("*.py")):
        target = destination / source.name
        shutil.copy2(source, target)
        copied.append(source.name)

    probe_source = ROOT / "tools" / "phase3_pppp_probe"
    probe_destination = destination / "tools" / "phase3_pppp_probe"
    probe_destination.mkdir(parents=True, exist_ok=True)
    for source in sorted(probe_source.glob("*.py")):
        target = probe_destination / source.name
        shutil.copy2(source, target)
        copied.append(str(target.relative_to(destination)))
    return copied


def iter_forbidden_paths(root: Path) -> Iterable[Path]:
    forbidden_names = {
        ".env",
        ".env.local",
        "options.json",
        "backend-api-token",
        "runtime-policy.json",
        "capabilities.json",
    }
    for path in root.rglob("*"):
        if path.is_file() and path.name.casefold() in forbidden_names:
            yield path


def ensure_runtime(runtime: Path) -> None:
    required = [
        runtime / "system/bin/linker64",
        runtime / "system/lib64/libc.so",
        runtime / "system/lib64/libdl.so",
        runtime / "data/local/tmp/yi-phase3g",
        runtime / "data/local/tmp/yi-online-status/android_pppp_online_probe",
        runtime / "data/local/tmp/yi-online-status/libPPPP_API.so",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit("required proven runtime artifact missing: " + ", ".join(missing))
    worker_dir = runtime / "data/local/tmp/yi-phase3g"
    if not any(path.is_file() for path in worker_dir.iterdir()):
        raise SystemExit("Phase 3G worker directory is empty")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare yi_home Docker build context")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    args = parser.parse_args()

    runtime = args.runtime_root.expanduser().resolve()
    app_dir = args.app_dir.expanduser().resolve()
    rootfs = app_dir / "rootfs"
    ensure_runtime(runtime)
    reset_rootfs(rootfs)

    app_destination = rootfs / "opt/yi-home/app"
    runtime_destination = rootfs / "opt/yi-home/runtime/bionic-root"
    copied_sources = copy_project_sources(app_destination)
    shutil.copytree(runtime, runtime_destination, symlinks=True)

    forbidden = list(iter_forbidden_paths(rootfs))
    if forbidden:
        for path in forbidden:
            if path.is_file():
                path.unlink()
        raise SystemExit("forbidden secret/state file was present in staged App context")

    # Preserve execute bits on the native worker and Android linker even when a
    # source filesystem has restrictive defaults.
    for path in (
        runtime_destination / "system/bin/linker64",
        runtime_destination / "data/local/tmp/yi-online-status/android_pppp_online_probe",
    ):
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    critical = {
        "android_linker64": runtime_destination / "system/bin/linker64",
        "bionic_libc": runtime_destination / "system/lib64/libc.so",
        "online_worker": runtime_destination / "data/local/tmp/yi-online-status/android_pppp_online_probe",
        "online_pppp_library": runtime_destination / "data/local/tmp/yi-online-status/libPPPP_API.so",
    }
    manifest = {
        "schema_version": 1,
        "source_commit": git_head(ROOT),
        "architecture": "amd64-host/aarch64-guest",
        "python_source_count": len(copied_sources),
        "critical_artifacts": {
            name: {
                "path": str(path.relative_to(rootfs)),
                "size": path.stat().st_size,
                "sha256": sha256(path),
            }
            for name, path in critical.items()
        },
        "secrets_exposed": False,
    }
    manifest_path = rootfs / "opt/yi-home/runtime-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o644)

    print(f"app_context={app_dir}")
    print(f"runtime_source={runtime}")
    print(f"python_source_count={len(copied_sources)}")
    print(f"runtime_manifest={manifest_path}")
    print("secret_files_copied=false")
    print("PHASE6D_APP_CONTEXT_PREPARE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
