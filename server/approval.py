from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class ApprovalError(PermissionError):
    """Raised when a draft call lacks valid single-use broker authorization."""


def canonical_fingerprint(arguments: dict[str, Any]) -> str:
    encoded = json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ApprovalStore:
    """Small file-backed approval ledger for the single-user demo."""

    def __init__(self, path: Path, ttl_seconds: int = 900) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _write(self, data: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        temporary.replace(self.path)

    def create_pending(self, context: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(24)
        now_value = datetime.now(UTC)
        now = now_value.isoformat()
        with self._lock:
            data = self._read()
            data[token] = {
                "status": "pending",
                "context": context,
                "created_at": now,
                "expires_at": (now_value + timedelta(seconds=self.ttl_seconds)).isoformat(),
                "argument_fingerprint": None,
            }
            self._write(data)
        return token

    def approve(self, token: str, arguments: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            record = data.get(token)
            if record is None:
                raise ApprovalError("Approval token is missing, expired, or no longer pending")
            if datetime.now(UTC) >= datetime.fromisoformat(record["expires_at"]):
                record["status"] = "expired"
                self._write(data)
                raise ApprovalError("Approval token has expired")
            for key in ("client_id", "sku_id"):
                expected = record["context"].get(key)
                if expected is not None and arguments.get(key) != expected:
                    raise ApprovalError(f"Approved {key} does not match pending context")
            fingerprint = canonical_fingerprint(arguments)
            if record["status"] == "approved":
                if record["argument_fingerprint"] != fingerprint:
                    raise ApprovalError(
                        "Previously approved arguments do not match this retry"
                    )
                return
            if record["status"] != "pending":
                raise ApprovalError("Approval token is expired or no longer pending")
            record["status"] = "approved"
            record["approved_at"] = datetime.now(UTC).isoformat()
            record["argument_fingerprint"] = fingerprint
            self._write(data)

    def deny(self, token: str) -> None:
        with self._lock:
            data = self._read()
            record = data.get(token)
            if record is None or record["status"] != "pending":
                raise ApprovalError("Approval token is missing or no longer pending")
            record["status"] = "denied"
            record["denied_at"] = datetime.now(UTC).isoformat()
            self._write(data)

    def consume(self, token: str, arguments: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            record = data.get(token)
            if record is None or record["status"] != "approved":
                raise ApprovalError("Draft creation requires a current broker approval")
            if datetime.now(UTC) >= datetime.fromisoformat(record["expires_at"]):
                record["status"] = "expired"
                self._write(data)
                raise ApprovalError("Approval token has expired")
            if record["argument_fingerprint"] != canonical_fingerprint(arguments):
                raise ApprovalError("Approved arguments do not match the draft request")
            record["status"] = "consumed"
            record["consumed_at"] = datetime.now(UTC).isoformat()
            self._write(data)

