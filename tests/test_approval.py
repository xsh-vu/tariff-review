import pytest

from server.approval import ApprovalError, ApprovalStore
from server import tools as server_tools


def arguments(token: str) -> dict:
    return {
        "client_id": "northfield-home-goods",
        "sku_id": "NF-DW-001",
        "declared_code": "9617.00.1000",
        "proposed_code": "7323.93.0080",
        "evidence_ids": ["N224817", "N241154"],
        "rationale": "Confirmed non-vacuum construction.",
        "route": "broker",
        "approval_token": token,
    }


def test_approval_is_exact_and_single_use(tmp_path) -> None:
    store = ApprovalStore(tmp_path / "approvals.json")
    token = store.create_pending(
        {"client_id": "northfield-home-goods", "sku_id": "NF-DW-001"}
    )
    approved = arguments(token)
    store.approve(token, approved)
    store.approve(token, approved)
    with pytest.raises(ApprovalError):
        store.consume(token, {**approved, "proposed_code": "3924.90.5650"})
    store.consume(token, approved)
    with pytest.raises(ApprovalError):
        store.consume(token, approved)


def test_denial_cannot_be_consumed(tmp_path) -> None:
    store = ApprovalStore(tmp_path / "approvals.json")
    token = store.create_pending(
        {"client_id": "northfield-home-goods", "sku_id": "NF-DW-001"}
    )
    store.deny(token)
    with pytest.raises(ApprovalError):
        store.consume(token, arguments(token))


def test_expired_token_cannot_be_approved(tmp_path) -> None:
    store = ApprovalStore(tmp_path / "approvals.json", ttl_seconds=0)
    token = store.create_pending(
        {"client_id": "northfield-home-goods", "sku_id": "NF-DW-001"}
    )
    with pytest.raises(ApprovalError, match="expired"):
        store.approve(token, arguments(token))


def test_draft_tool_requires_approval_and_does_not_store_raw_token(
    tmp_path, monkeypatch
) -> None:
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    store = ApprovalStore(tmp_path / "approvals.json")
    monkeypatch.setattr(server_tools, "approval_store", store)
    monkeypatch.setattr(server_tools, "PROJECT_ROOT", tmp_path)
    token = store.create_pending(
        {"client_id": "northfield-home-goods", "sku_id": "NF-DW-001"}
    )
    approved = arguments(token)
    with pytest.raises(ApprovalError):
        server_tools.draft_correction(**approved)
    store.approve(token, approved)
    draft = server_tools.draft_correction(**approved)
    assert draft["status"] == "draft_only"
    assert draft["not_filed"] is True
    assert "approval_token" not in draft
    assert draft["approval_token_sha256"] != token
    with pytest.raises(ApprovalError):
        server_tools.draft_correction(**approved)
