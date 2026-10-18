import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agent.client import (
    LiveConfigurationError,
    OpenAIConfig,
    TariffReviewClient,
)
from agent.fixture_review import FixtureReviewer
from data.repository import Repository
from server.approval import ApprovalStore


class FakeResponses:
    def __init__(self, omit_ruling: str | None = None) -> None:
        self.omit_ruling = omit_ruling
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        request = json.loads(kwargs["input"])
        proposal = FixtureReviewer().review(
            request["sku_ids"], request.get("description_overrides")
        )["proposal"]
        proposal["run_id"] = request["run_id"]
        repository = Repository()

        def call(name, arguments, output):
            return SimpleNamespace(
                type="mcp_call",
                name=name,
                arguments=json.dumps(arguments),
                output=json.dumps(output),
                error=None,
            )

        output = [
            call(
                "get_catalog",
                {
                    "client_id": "northfield-home-goods",
                    "sku_ids": request["sku_ids"],
                    "description_overrides": request.get("description_overrides", {}),
                },
                repository.get_catalog("northfield-home-goods", request["sku_ids"]),
            ),
            call(
                "get_entries",
                {"client_id": "northfield-home-goods", "sku_id": "NF-DW-001"},
                repository.get_entries("northfield-home-goods", "NF-DW-001"),
            ),
            call("search_hts", {"query": "drinkware"}, repository.rates),
        ]
        for ruling_id in proposal["findings"][0]["rulings_cited"]:
            if ruling_id != self.omit_ruling:
                output.append(
                    call(
                        "get_ruling",
                        {"ruling_id": ruling_id},
                        repository.get_ruling(ruling_id),
                    )
                )
        output.append(SimpleNamespace(type="message", content=[]))
        return SimpleNamespace(
            id="resp_test",
            model="gpt-6-astra",
            status="completed",
            output=output,
            output_text=json.dumps(proposal),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
        )


class FakeOpenAI:
    def __init__(self, omit_ruling: str | None = None) -> None:
        self.responses = FakeResponses(omit_ruling)


class FakeApprovalResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "previous_response_id" not in kwargs:
            arguments = json.loads(kwargs["input"])
            return SimpleNamespace(
                id="resp_pending",
                status="completed",
                output=[
                    SimpleNamespace(
                        type="mcp_approval_request",
                        id="approval_1",
                        name="draft_correction",
                        arguments=json.dumps(arguments),
                    )
                ],
            )
        return SimpleNamespace(
            id="resp_approved",
            status="completed",
            output=[
                SimpleNamespace(
                    type="mcp_call",
                    name="draft_correction",
                    error=None,
                    output=json.dumps(
                        {"draft_id": "DRAFT-TEST", "status": "draft_only", "not_filed": True}
                    ),
                )
            ],
            output_text="",
        )


class FakeApprovalOpenAI:
    def __init__(self) -> None:
        self.responses = FakeApprovalResponses()


def config() -> OpenAIConfig:
    return OpenAIConfig(
        model="gpt-6-astra",
        server_url=None,
        tunnel_id="tunnel_test",
        authorization=None,
        input_cost_per_million=None,
        output_cost_per_million=None,
    )


def test_review_uses_strict_schema_allowlist_and_fetched_provenance(tmp_path) -> None:
    fake = FakeOpenAI()
    client = TariffReviewClient(config=config(), openai_client=fake)
    result = client.review(["NF-DW-001"])
    request = fake.responses.calls[0]
    assert request["text"]["format"]["strict"] is True
    assert "draft_correction" not in request["tools"][0]["allowed_tools"]
    assert request["tools"][0]["tunnel_id"] == "tunnel_test"
    assert result["potential_overpayment_total"] == "12480.00"
    assert result["execution"]["api_usage"]["total_tokens"] == 150
    assert result["execution"]["api_cost_usd"] is None
    assert {call["name"] for call in result["mcp_trace"]} >= {
        "get_catalog",
        "get_entries",
        "search_hts",
        "get_ruling",
    }


def test_review_rejects_a_known_but_unfetched_citation() -> None:
    client = TariffReviewClient(
        config=config(), openai_client=FakeOpenAI(omit_ruling="N321134")
    )
    with pytest.raises(ValueError, match="unfetched rulings"):
        client.review(["NF-DW-001"])


def test_review_requires_description_overrides_in_catalog_call() -> None:
    fake = FakeOpenAI()
    client = TariffReviewClient(config=config(), openai_client=fake)
    result = client.review(
        ["NF-DW-003"],
        {
            "NF-DW-003": (
                "14 oz complete stainless-steel vacuum flask with "
                "laboratory-confirmed sub-atmospheric pressure between its walls."
            )
        },
    )
    finding = result["proposal"]["findings"][0]
    assert finding["outcome"] == "potential_underpayment"
    request = json.loads(fake.responses.calls[0]["input"])
    catalog_call = next(
        call for call in result["mcp_trace"] if call["name"] == "get_catalog"
    )
    assert catalog_call["arguments"]["description_overrides"] == request[
        "description_overrides"
    ]


def test_public_remote_config_requires_https_and_authorization(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-astra")
    monkeypatch.setenv("MCP_SERVER_URL", "https://mcp.example.test/mcp")
    monkeypatch.delenv("MCP_TUNNEL_ID", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    with pytest.raises(LiveConfigurationError, match="MCP_AUTH_TOKEN"):
        OpenAIConfig.from_env()


def test_draft_flow_uses_one_mcp_approval_continuation(tmp_path) -> None:
    fake = FakeApprovalOpenAI()
    store = ApprovalStore(tmp_path / "approvals.json")
    client = TariffReviewClient(
        config=config(), approval_store=store, openai_client=fake
    )
    finding = FixtureReviewer().review(["NF-DW-001"])["proposal"]["findings"][0]
    pending = client.request_draft(finding)
    assert pending.tool_name == "draft_correction"
    assert fake.responses.calls[0]["tools"][0]["require_approval"] == "always"
    result = client.resolve_draft(pending, approve=True)
    continuation = fake.responses.calls[1]
    assert continuation["previous_response_id"] == "resp_pending"
    assert continuation["tools"][0]["allowed_tools"] == ["draft_correction"]
    assert continuation["tools"][0]["require_approval"] == "always"
    assert continuation["input"] == [
        {
            "type": "mcp_approval_response",
            "approve": True,
            "approval_request_id": "approval_1",
        }
    ]
    assert result["status"] == "draft_created"
    assert result["output"]["not_filed"] is True


def test_usage_cost_includes_cached_and_cache_write_tokens() -> None:
    priced = OpenAIConfig(
        model="gpt-6.1-sol",
        server_url=None,
        tunnel_id="tunnel_test",
        authorization=None,
        input_cost_per_million=Decimal("2.00"),
        cached_input_cost_per_million=Decimal("0.10"),
        cache_write_cost_per_million=Decimal("2.50"),
        output_cost_per_million=Decimal("10.00"),
        pricing_observed_at="2026-10-18",
        pricing_source_url="https://developers.openai.com/api/docs/pricing",
    )
    client = TariffReviewClient(config=priced, openai_client=FakeOpenAI())
    response = SimpleNamespace(
        id="resp_usage",
        model="gpt-6.1-sol",
        service_tier="default",
        usage=SimpleNamespace(
            input_tokens=100,
            input_tokens_details=SimpleNamespace(
                cached_tokens=10, cache_write_tokens=20
            ),
            output_tokens=50,
            output_tokens_details=SimpleNamespace(reasoning_tokens=25),
            total_tokens=150,
        ),
    )
    record = client._usage_record(response, 1.2345)
    assert record["api_usage"]["uncached_input_tokens"] == 70
    assert record["api_usage"]["reasoning_tokens"] == 25
    assert record["api_cost_usd"] == "0.000691"
    assert record["cost_basis"]["pricing_observed_at"] == "2026-10-18"


def test_env_config_uses_dated_pricing_registry(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("MCP_TUNNEL_ID", "tunnel_test")
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    for name in (
        "OPENAI_INPUT_COST_PER_MILLION",
        "OPENAI_CACHED_INPUT_COST_PER_MILLION",
        "OPENAI_CACHE_WRITE_COST_PER_MILLION",
        "OPENAI_OUTPUT_COST_PER_MILLION",
        "OPENAI_PRICING_OBSERVED_AT",
        "OPENAI_PRICING_SOURCE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    resolved = OpenAIConfig.from_env()
    assert resolved.input_cost_per_million == Decimal("2.00")
    assert resolved.cached_input_cost_per_million == Decimal("0.10")
    assert resolved.cache_write_cost_per_million == Decimal("2.50")
    assert resolved.output_cost_per_million == Decimal("10.00")
    assert resolved.pricing_observed_at == "2026-10-18"
