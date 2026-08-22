#!/usr/bin/env python3
"""Persistence adapter for the reusable YI Add-on backend.

The proven YiAddonBackend remains responsible for discovery, runtime lifecycle,
reprobe and media publication. This subclass adds only durable runtime intent
and reconciliation after successful discovery.
"""

from __future__ import annotations

from typing import Any

from yi_addon_backend import YiAddonBackend, _utc_now
from yi_runtime_policy import YiRuntimePolicyStore


class YiPersistentAddonBackend(YiAddonBackend):
    """YiAddonBackend with durable per-camera desired-running policy."""

    def __init__(self, *, runtime_policy: YiRuntimePolicyStore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.runtime_policy = runtime_policy
        self._policy_error: dict[str, str] | None = None
        self._restore_pending: set[str] = set()
        self._last_reconcile_at: str | None = None
        self._last_reconcile_restored = 0
        self._last_reconcile_failed = 0
        try:
            self._restore_pending = set(self.runtime_policy.desired_running_ids())
        except (RuntimeError, ValueError, OSError):
            self._policy_error = {
                "category": "runtime_policy_error",
                "message": "Persistent runtime policy could not be read.",
            }

    def _policy_desired(self, stable_id: str) -> bool | None:
        try:
            return self.runtime_policy.desired_running(stable_id)
        except (RuntimeError, ValueError, OSError):
            return None

    def _persist_intent(self, stable_id: str, desired: bool) -> bool:
        try:
            self.runtime_policy.set_desired_running(stable_id, desired)
        except (RuntimeError, ValueError, OSError):
            with self._lock:
                self._policy_error = {
                    "category": "runtime_policy_error",
                    "message": "Persistent runtime policy could not be updated.",
                }
            return False
        with self._lock:
            self._policy_error = None
            if desired:
                self._restore_pending.add(stable_id)
            else:
                self._restore_pending.discard(stable_id)
        return True

    def _reconcile_runtime_policy(self) -> dict[str, Any]:
        if self.lifecycle is None:
            return {
                "enabled": True,
                "desired_running_count": 0,
                "restored_count": 0,
                "pending_count": 0,
                "failed_count": 0,
                "secrets_exposed": False,
            }
        try:
            desired = set(self.runtime_policy.desired_running_ids())
        except (RuntimeError, ValueError, OSError):
            with self._lock:
                self._policy_error = {
                    "category": "runtime_policy_error",
                    "message": "Persistent runtime policy could not be read.",
                }
            return {
                "enabled": True,
                "desired_running_count": 0,
                "restored_count": 0,
                "pending_count": len(self._restore_pending),
                "failed_count": 0,
                "secrets_exposed": False,
            }

        with self._lock:
            available = set(self._cameras)
        pending = desired - available
        restored = 0
        failed = 0
        for stable_id in sorted(desired & available):
            try:
                runtime = self.lifecycle.start(stable_id)
            except (RuntimeError, ValueError, OSError):
                pending.add(stable_id)
                failed += 1
                continue
            if runtime.get("desired_running") is True:
                restored += 1
            else:
                pending.add(stable_id)
                failed += 1

        with self._lock:
            self._restore_pending = pending
            self._last_reconcile_at = _utc_now()
            self._last_reconcile_restored = restored
            self._last_reconcile_failed = failed
            self._policy_error = None
        return {
            "enabled": True,
            "desired_running_count": len(desired),
            "restored_count": restored,
            "pending_count": len(pending),
            "failed_count": failed,
            "secrets_exposed": False,
        }

    def discover(self, *, fetch_tnp: bool = True) -> dict[str, Any]:
        result = super().discover(fetch_tnp=fetch_tnp)
        result["runtime_restore"] = self._reconcile_runtime_policy()
        return result

    def _intent_write_error(self) -> tuple[int, dict[str, Any]]:
        return 500, {
            "ok": False,
            "error": {
                "code": "runtime_policy_write_failed",
                "message": "The requested runtime intent could not be persisted.",
            },
            "secrets_exposed": False,
        }

    def start_camera(self, stable_id: str) -> tuple[int, dict[str, Any]]:
        if not self._camera_exists(stable_id):
            return super().start_camera(stable_id)
        if self.lifecycle is None:
            return super().start_camera(stable_id)
        if not self._persist_intent(stable_id, True):
            return self._intent_write_error()
        status, payload = super().start_camera(stable_id)
        payload["persisted_desired_running"] = True
        if status == 200:
            with self._lock:
                self._restore_pending.discard(stable_id)
        return status, payload

    def stop_camera(self, stable_id: str) -> tuple[int, dict[str, Any]]:
        if not self._camera_exists(stable_id):
            return super().stop_camera(stable_id)
        if self.lifecycle is None:
            return super().stop_camera(stable_id)
        if not self._persist_intent(stable_id, False):
            return self._intent_write_error()
        status, payload = super().stop_camera(stable_id)
        payload["persisted_desired_running"] = False
        return status, payload

    def restart_camera(self, stable_id: str) -> tuple[int, dict[str, Any]]:
        if not self._camera_exists(stable_id):
            return super().restart_camera(stable_id)
        if self.lifecycle is None:
            return super().restart_camera(stable_id)
        if not self._persist_intent(stable_id, True):
            return self._intent_write_error()
        status, payload = super().restart_camera(stable_id)
        payload["persisted_desired_running"] = True
        if status == 200:
            with self._lock:
                self._restore_pending.discard(stable_id)
        return status, payload

    def _add_intent(self, payload: dict[str, Any] | None, key: str) -> dict[str, Any] | None:
        if payload is None:
            return None
        item = payload.get(key)
        if isinstance(item, dict):
            stable_id = item.get("stable_id")
            if isinstance(stable_id, str):
                item["persisted_desired_running"] = self._policy_desired(stable_id)
        return payload

    def camera(self, stable_id: str) -> dict[str, Any] | None:
        return self._add_intent(super().camera(stable_id), "camera")

    def camera_status(self, stable_id: str) -> dict[str, Any] | None:
        return self._add_intent(super().camera_status(stable_id), "status")

    def cameras(self) -> dict[str, Any]:
        payload = super().cameras()
        for item in payload.get("cameras", []):
            if isinstance(item, dict) and isinstance(item.get("stable_id"), str):
                item["persisted_desired_running"] = self._policy_desired(item["stable_id"])
        return payload

    def health(self) -> dict[str, Any]:
        payload = super().health()
        try:
            policy = self.runtime_policy.safe_status()
        except (RuntimeError, ValueError, OSError):
            policy = {
                "enabled": True,
                "schema_version": 1,
                "desired_running_count": 0,
                "updated_at": None,
                "secrets_exposed": False,
            }
        with self._lock:
            policy.update(
                {
                    "pending_restore_count": len(self._restore_pending),
                    "last_reconcile_at": self._last_reconcile_at,
                    "last_reconcile_restored": self._last_reconcile_restored,
                    "last_reconcile_failed": self._last_reconcile_failed,
                    "last_error": dict(self._policy_error) if self._policy_error is not None else None,
                }
            )
        payload["runtime_persistence"] = policy
        return payload
