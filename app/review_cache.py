from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from agent.client import MCP_SERVER_LABEL, REVIEW_TOOLS, TariffReviewClient
from agent.schema import strict_response_format
from data.repository import PROJECT_ROOT, Repository


REVIEW_RESULT_CACHE_VERSION = 1
REVIEW_RESULT_CACHE_TTL_SECONDS = 1800.0
REVIEW_RESULT_CACHE_MAX_ENTRIES = 8

_CACHE_DEPENDENCY_PATHS = (
    "agent/client.py",
    "agent/instructions.md",
    "agent/schema.py",
    "data/duty.py",
    "data/repository.py",
    "data/source_data/entries.json",
    "data/source_data/hts_rates.json",
    "data/source_data/products.json",
    "data/source_data/rulings.json",
    "server/mcp_server.py",
    "server/tools.py",
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _dependency_digests(project_root: Path = PROJECT_ROOT) -> dict[str, str]:
    return {
        relative_path: _sha256_bytes((project_root / relative_path).read_bytes())
        for relative_path in _CACHE_DEPENDENCY_PATHS
    }


def _openai_sdk_version() -> str:
    try:
        return version("openai")
    except PackageNotFoundError:
        return "unknown"


def build_review_fingerprint(
    client: TariffReviewClient,
    repository: Repository,
    sku_ids: list[str],
    description_overrides: dict[str, str],
) -> str:
    """Hash every non-secret input that can materially change a live review."""
    server_identity = client.config.tunnel_id or client.config.server_url or ""
    payload = {
        "cache_contract_version": REVIEW_RESULT_CACHE_VERSION,
        "client_id": "northfield-home-goods",
        "sku_ids": list(sku_ids),
        "description_overrides": description_overrides,
        "model": client.config.model,
        "service_tier": client.config.service_tier,
        "mcp": {
            "server_label": MCP_SERVER_LABEL,
            "server_identity_sha256": _sha256_text(server_identity),
            "allowed_tools": REVIEW_TOOLS,
        },
        "instructions_sha256": _sha256_text(client.instructions),
        "structured_output_schema": strict_response_format(),
        "source_revision": repository.source_revision,
        "dependency_digests": _dependency_digests(),
        "openai_sdk_version": _openai_sdk_version(),
    }
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return _sha256_text(canonical)


def _is_cacheable(review: dict[str, Any]) -> bool:
    execution = review.get("execution")
    remote_mcp = review.get("remote_mcp")
    return bool(
        review.get("structured_output_validated") is True
        and isinstance(execution, dict)
        and execution.get("mode") == "live_responses_api_remote_mcp"
        and execution.get("response_id")
        and isinstance(remote_mcp, dict)
        and set(remote_mcp.get("successful_calls", [])) >= set(REVIEW_TOOLS)
    )


def mark_live_review(review: dict[str, Any]) -> dict[str, Any]:
    marked = deepcopy(review)
    marked["result_cache"] = {
        "hit": False,
        "label": "New live OpenAI + MCP execution",
    }
    return marked


def store_review_result(
    cache: dict[str, dict[str, Any]],
    fingerprint: str,
    review: dict[str, Any],
    *,
    now: float | None = None,
) -> None:
    """Store only complete, validated live results; never approval state."""
    if not _is_cacheable(review):
        raise ValueError("Only validated live OpenAI + MCP reviews may be cached")
    stored_review = deepcopy(review)
    stored_review.pop("result_cache", None)
    cache[fingerprint] = {
        "stored_at_epoch": time.time() if now is None else now,
        "review": stored_review,
    }
    if len(cache) > REVIEW_RESULT_CACHE_MAX_ENTRIES:
        oldest = sorted(
            cache,
            key=lambda key: float(cache[key].get("stored_at_epoch", 0.0)),
        )
        for key in oldest[: len(cache) - REVIEW_RESULT_CACHE_MAX_ENTRIES]:
            cache.pop(key, None)


def get_review_result(
    cache: dict[str, dict[str, Any]],
    fingerprint: str,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    current_time = time.time() if now is None else now
    entry = cache.get(fingerprint)
    if not isinstance(entry, dict):
        return None
    stored_at = entry.get("stored_at_epoch")
    review = entry.get("review")
    if not isinstance(stored_at, (int, float)) or not isinstance(review, dict):
        cache.pop(fingerprint, None)
        return None
    age_seconds = max(0.0, current_time - float(stored_at))
    if age_seconds > REVIEW_RESULT_CACHE_TTL_SECONDS or not _is_cacheable(review):
        cache.pop(fingerprint, None)
        return None

    reused = deepcopy(review)
    execution = reused["execution"]
    reused["result_cache"] = {
        "hit": True,
        "label": "Reused validated session review",
        "reused_at": datetime.fromtimestamp(
            current_time, tz=timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "age_seconds": round(age_seconds, 3),
        "original_measured_at": execution.get("measured_at"),
        "original_response_id": execution.get("response_id"),
        "incremental_openai_requests": 0,
        "incremental_mcp_calls": 0,
        "incremental_api_cost_usd": "0.000000",
    }
    return reused
