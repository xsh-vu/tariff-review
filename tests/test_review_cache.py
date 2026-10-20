from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import app.review_cache as review_cache
from app.review_cache import (
    REVIEW_RESULT_CACHE_MAX_ENTRIES,
    REVIEW_RESULT_CACHE_TTL_SECONDS,
    build_review_fingerprint,
    get_review_result,
    mark_live_review,
    store_review_result,
)
from data.repository import Repository


def fake_client(*, model: str = "gpt-6.1-sol", authorization: str | None = None):
    return SimpleNamespace(
        config=SimpleNamespace(
            model=model,
            service_tier="default",
            tunnel_id="tunnel_demo",
            server_url=None,
            authorization=authorization,
        ),
        instructions="Use verified tariff evidence.",
    )


def validated_review() -> dict:
    return {
        "structured_output_validated": True,
        "proposal": {"findings": []},
        "remote_mcp": {
            "successful_calls": [
                "get_catalog",
                "get_entries",
                "search_hts_batch",
                "search_rulings_batch",
            ]
        },
        "execution": {
            "mode": "live_responses_api_remote_mcp",
            "response_id": "resp_original",
            "measured_at": "2026-10-19T12:00:00Z",
            "api_cost_usd": "0.012345",
        },
    }


def test_fingerprint_changes_with_review_inputs_but_not_credentials(monkeypatch) -> None:
    monkeypatch.setattr(review_cache, "_dependency_digests", lambda: {"files": "v1"})
    repository = Repository()
    base = build_review_fingerprint(
        fake_client(authorization="secret-one"),
        repository,
        ["NF-DW-001"],
        {},
    )

    assert base == build_review_fingerprint(
        fake_client(authorization="secret-two"),
        repository,
        ["NF-DW-001"],
        {},
    )
    assert base != build_review_fingerprint(
        fake_client(model="gpt-6-astra"),
        repository,
        ["NF-DW-001"],
        {},
    )
    assert base != build_review_fingerprint(
        fake_client(),
        repository,
        ["NF-DW-001"],
        {"NF-DW-001": "Edited material description"},
    )
    assert base != build_review_fingerprint(
        fake_client(),
        repository,
        ["NF-DW-002", "NF-DW-001"],
        {},
    )


def test_validated_review_round_trip_is_labeled_and_isolated() -> None:
    cache: dict = {}
    original = validated_review()
    store_review_result(cache, "fingerprint", original, now=100.0)

    reused = get_review_result(cache, "fingerprint", now=106.5)

    assert reused is not None
    assert reused["result_cache"] == {
        "hit": True,
        "label": "Reused validated session review",
        "reused_at": "1970-01-01T00:01:46.500000Z",
        "age_seconds": 6.5,
        "original_measured_at": "2026-10-19T12:00:00Z",
        "original_response_id": "resp_original",
        "incremental_openai_requests": 0,
        "incremental_mcp_calls": 0,
        "incremental_api_cost_usd": "0.000000",
    }
    reused["proposal"]["findings"].append({"mutated": True})
    assert cache["fingerprint"]["review"]["proposal"]["findings"] == []
    assert "result_cache" not in original


def test_expired_or_invalid_review_is_not_reused() -> None:
    cache: dict = {}
    store_review_result(cache, "expired", validated_review(), now=100.0)
    assert (
        get_review_result(
            cache,
            "expired",
            now=100.0 + REVIEW_RESULT_CACHE_TTL_SECONDS + 0.001,
        )
        is None
    )
    assert "expired" not in cache

    invalid = validated_review()
    invalid["structured_output_validated"] = False
    with pytest.raises(ValueError, match="validated live"):
        store_review_result(cache, "invalid", invalid, now=200.0)


def test_cache_is_bounded_and_live_results_are_marked() -> None:
    cache: dict = {}
    for index in range(REVIEW_RESULT_CACHE_MAX_ENTRIES + 2):
        review = deepcopy(validated_review())
        review["execution"]["response_id"] = f"resp_{index}"
        store_review_result(cache, f"key-{index}", review, now=float(index))

    assert len(cache) == REVIEW_RESULT_CACHE_MAX_ENTRIES
    assert "key-0" not in cache
    assert "key-1" not in cache
    assert mark_live_review(validated_review())["result_cache"]["hit"] is False
