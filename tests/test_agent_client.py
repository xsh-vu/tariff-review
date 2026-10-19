import json
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agent.client import (
    LiveConfigurationError,
    OpenAIConfig,
    ResponseValidationError,
    TariffReviewClient,
)
from agent.fixture_review import FixtureReviewer
from data.repository import Repository
from server.approval import ApprovalStore


class FakeResponses:
    def __init__(
        self,
        omit_ruling: str | None = None,
        discovery_tools: list[str] | None = None,
    ) -> None:
        self.omit_ruling = omit_ruling
        self.discovery_tools = discovery_tools
        self.calls = []
        self.stream_delay = 0.0

    def create(self, **kwargs):
        self.calls.append(kwargs)
        request_input = kwargs["input"]
        reused_discovery = isinstance(request_input, list)
        if reused_discovery:
            user_item = request_input[-1]
            request = json.loads(user_item["content"][0]["text"])
        else:
            request = json.loads(request_input)
        proposal = FixtureReviewer().review(
            request["sku_ids"], request.get("description_overrides")
        )["proposal"]
        proposal["run_id"] = request["run_id"]
        proposal.pop("status")
        for finding in proposal["findings"]:
            finding.pop("declared_code")
        repository = Repository()

        def call(name, arguments, output):
            return SimpleNamespace(
                id=f"mcp_{name}_{len(output_items)}",
                type="mcp_call",
                name=name,
                arguments=json.dumps(arguments),
                output=json.dumps(output),
                error=None,
            )

        output_items = []
        if not reused_discovery:
            discovered_names = (
                self.discovery_tools
                if self.discovery_tools is not None
                else kwargs["tools"][0]["allowed_tools"]
            )
            output_items.append(
                SimpleNamespace(
                    id="mcpl_test",
                    type="mcp_list_tools",
                    server_label="harbor_crane_tariff_review",
                    tools=[
                        SimpleNamespace(
                            name=name,
                            input_schema={
                                "type": "object",
                                "properties": {},
                                "additionalProperties": False,
                            },
                            annotations={"readOnlyHint": True},
                            description=f"Test schema for {name}",
                        )
                        for name in discovered_names
                    ],
                    error=None,
                )
            )
        catalog_records = repository.get_catalog(
            "northfield-home-goods", request["sku_ids"]
        )
        if hasattr(self, "catalog_declared_code_override"):
            for record in catalog_records:
                record["declared_code"] = self.catalog_declared_code_override
        output_items.extend(
            [
                call(
                    "get_catalog",
                    {
                        "client_id": "northfield-home-goods",
                        "sku_ids": request["sku_ids"],
                        "description_overrides": request.get(
                            "description_overrides", {}
                        ),
                    },
                    {"records": catalog_records},
                ),
                call(
                    "get_entries",
                    {
                        "client_id": "northfield-home-goods",
                        "sku_ids": request["sku_ids"],
                    },
                    [
                        entry
                        for sku_id in request["sku_ids"]
                        for entry in repository.get_entries(
                            "northfield-home-goods", sku_id
                        )
                    ],
                ),
                call(
                    "search_hts_batch",
                    {"queries": ["selected products"]},
                    {
                        "results": [
                            {
                                "query": "selected products",
                                "matches": repository.rates,
                            }
                        ]
                    },
                ),
            ]
        )
        ruling_ids = sorted(
            {
                ruling_id
                for finding in proposal["findings"]
                for ruling_id in finding["rulings_cited"]
                if ruling_id != self.omit_ruling
            }
        )
        output_items.append(
            call(
                "search_rulings_batch",
                {"queries": ["selected product evidence"]},
                {
                    "results": [
                        {
                            "query": "selected product evidence",
                            "matches": [
                                repository.get_ruling(ruling_id)
                                for ruling_id in ruling_ids
                            ],
                        }
                    ]
                },
            )
        )
        output_items.append(SimpleNamespace(type="message", content=[]))
        response = SimpleNamespace(
            id="resp_test",
            model="gpt-6-astra",
            status="completed",
            output=output_items,
            output_text=json.dumps(proposal),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
        )
        if not kwargs.get("stream"):
            return response

        def events():
            yield SimpleNamespace(type="response.created", response=response)
            yield SimpleNamespace(type="response.in_progress", response=response)
            if self.stream_delay:
                time.sleep(self.stream_delay)
            for index, item in enumerate(output_items):
                if item.type == "mcp_list_tools":
                    yield SimpleNamespace(
                        type="response.mcp_list_tools.in_progress",
                        item_id=item.id,
                        output_index=index,
                    )
                    yield SimpleNamespace(
                        type="response.mcp_list_tools.completed",
                        item_id=item.id,
                        output_index=index,
                    )
                elif item.type == "mcp_call":
                    yield SimpleNamespace(
                        type="response.output_item.added",
                        item=item,
                        output_index=index,
                    )
                    yield SimpleNamespace(
                        type="response.mcp_call_arguments.done",
                        item_id=item.id,
                        output_index=index,
                        arguments=item.arguments,
                    )
                    yield SimpleNamespace(
                        type="response.mcp_call.in_progress",
                        item_id=item.id,
                        output_index=index,
                    )
                    yield SimpleNamespace(
                        type="response.mcp_call.completed",
                        item_id=item.id,
                        output_index=index,
                    )
                elif item.type == "message":
                    yield SimpleNamespace(
                        type="response.output_item.added",
                        item=item,
                        output_index=index,
                    )
            yield SimpleNamespace(type="response.output_text.done")
            yield SimpleNamespace(type="response.completed", response=response)

        return events()


class FakeOpenAI:
    def __init__(
        self,
        omit_ruling: str | None = None,
        discovery_tools: list[str] | None = None,
    ) -> None:
        self.responses = FakeResponses(omit_ruling, discovery_tools)


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
    progress_messages = []
    result = client.review(
        ["NF-DW-001"], progress_callback=progress_messages.append
    )
    request = fake.responses.calls[0]
    assert request["stream"] is True
    assert request["text"]["format"]["strict"] is True
    assert request["tools"][0]["allowed_tools"] == [
        "get_catalog",
        "get_entries",
        "search_hts_batch",
        "search_rulings_batch",
    ]
    assert "compute_duty_delta" not in request["tools"][0]["allowed_tools"]
    assert request["tools"][0]["tunnel_id"] == "tunnel_test"
    assert result["potential_overpayment_total"] == "12480.00"
    assert result["execution"]["api_usage"]["total_tokens"] == 150
    assert result["execution"]["api_cost_usd"] is None
    breakdown = result["execution"]["latency_breakdown"]
    assert breakdown["event_timeline"]
    assert {segment["tool"] for segment in breakdown["segments"] if segment.get("tool")} == {
        "get_catalog",
        "get_entries",
        "search_hts_batch",
        "search_rulings_batch",
    }
    assert "overlap" in breakdown["note"]
    assert result["review_scope"]["source_revision"] == "2026 HTS Revision 21"
    assert result["proposal"]["status"] == "complete"
    assert result["proposal"]["findings"][0]["declared_code"] == "9617.00.1000"
    assert {call["name"] for call in result["mcp_trace"]} >= {
        "get_catalog",
        "get_entries",
        "search_hts_batch",
        "search_rulings_batch",
    }
    catalog_calls = [
        call for call in result["mcp_trace"] if call["name"] == "get_catalog"
    ]
    entry_calls = [
        call for call in result["mcp_trace"] if call["name"] == "get_entries"
    ]
    assert len(catalog_calls) == 1
    assert catalog_calls[0]["arguments"]["sku_ids"] == ["NF-DW-001"]
    assert len(entry_calls) == 1
    assert entry_calls[0]["arguments"]["sku_ids"] == ["NF-DW-001"]
    assert any("Responses API" in message for message in progress_messages)
    assert any("MCP · get_catalog" in message for message in progress_messages)
    assert any(
        "DutyCalculator.compute_duty_delta" in message
        for message in progress_messages
    )
    assert progress_messages[-1].startswith("Audit record")


def test_review_reports_a_heartbeat_while_stream_is_quiet(monkeypatch) -> None:
    import agent.client as client_module

    fake = FakeOpenAI()
    fake.responses.stream_delay = 0.03
    monkeypatch.setattr(client_module, "REVIEW_PROGRESS_HEARTBEAT_SECONDS", 0.01)
    progress_messages: list[str] = []

    TariffReviewClient(config=config(), openai_client=fake).review(
        ["NF-DW-001"], progress_callback=progress_messages.append
    )

    assert any(message.startswith("Still working") for message in progress_messages)
    assert any("MCP · get_catalog · call in progress" in message for message in progress_messages)
    assert any("MCP · get_catalog · completed" in message for message in progress_messages)


def test_review_reuses_only_matching_recent_mcp_discovery() -> None:
    fake = FakeOpenAI()
    client = TariffReviewClient(config=config(), openai_client=fake)

    first = client.review(["NF-DW-001"])
    second = client.review(["NF-DW-001"])

    assert first["remote_mcp"]["tool_discovery_reused"] is False
    assert second["remote_mcp"]["tool_discovery_reused"] is True
    second_input = fake.responses.calls[1]["input"]
    assert isinstance(second_input, list)
    assert len(second_input) == 2
    assert second_input[0]["type"] == "mcp_list_tools"
    assert {
        tool["name"] for tool in second_input[0]["tools"]
    } == set(fake.responses.calls[1]["tools"][0]["allowed_tools"])
    assert second_input[-1]["role"] == "user"
    assert second["remote_mcp"]["tool_discovery"] == first["remote_mcp"][
        "tool_discovery"
    ]


def test_review_discovery_cache_can_be_restored_by_a_new_client() -> None:
    fake = FakeOpenAI()
    first_client = TariffReviewClient(config=config(), openai_client=fake)

    first_client.review(["NF-DW-001"])
    state = first_client.export_review_discovery_cache()
    assert state is not None
    assert "authorization" not in state

    second_client = TariffReviewClient(config=config(), openai_client=fake)
    assert second_client.restore_review_discovery_cache(state) is True
    result = second_client.review(["NF-DW-001"])

    assert isinstance(fake.responses.calls[1]["input"], list)
    assert result["remote_mcp"]["tool_discovery_reused"] is True


def test_review_discovery_cache_rejects_a_changed_tool_policy() -> None:
    fake = FakeOpenAI()
    client = TariffReviewClient(config=config(), openai_client=fake)
    client.review(["NF-DW-001"])
    state = client.export_review_discovery_cache()
    assert state is not None
    state["allowed_tools"] = ["get_catalog"]

    fresh_client = TariffReviewClient(config=config(), openai_client=fake)
    assert fresh_client.restore_review_discovery_cache(state) is False


def test_review_rejects_stale_mcp_discovery_with_restart_guidance() -> None:
    fake = FakeOpenAI(discovery_tools=["get_catalog"])
    client = TariffReviewClient(config=config(), openai_client=fake)

    with pytest.raises(ResponseValidationError, match="Restart the local MCP server"):
        client.review(["NF-DW-001"])
    assert client.export_review_discovery_cache() is None


def test_review_does_not_reuse_expired_mcp_discovery() -> None:
    fake = FakeOpenAI()
    client = TariffReviewClient(config=config(), openai_client=fake)

    client.review(["NF-DW-001"])
    client._review_mcp_discovery_expires_at = 0.0
    second = client.review(["NF-DW-001"])

    assert isinstance(fake.responses.calls[1]["input"], str)
    assert second["remote_mcp"]["tool_discovery_reused"] is False


def test_review_requests_one_complete_catalog_and_entry_batch() -> None:
    fake = FakeOpenAI()
    client = TariffReviewClient(config=config(), openai_client=fake)
    sku_ids = ["NF-DW-001", "NF-DW-002", "NF-DW-003", "NF-DW-004"]

    result = client.review(sku_ids)
    prompt = json.loads(fake.responses.calls[0]["input"])
    catalog_calls = [
        call for call in result["mcp_trace"] if call["name"] == "get_catalog"
    ]
    entry_calls = [
        call for call in result["mcp_trace"] if call["name"] == "get_entries"
    ]

    assert all("exactly once" in rule for rule in prompt["required_tool_behavior"][:2])
    assert [call["arguments"]["sku_ids"] for call in catalog_calls] == [sku_ids]
    assert [call["arguments"]["sku_ids"] for call in entry_calls] == [sku_ids]


def test_review_accepts_an_added_back_product_at_the_end_of_selection() -> None:
    fake = FakeOpenAI()
    client = TariffReviewClient(config=config(), openai_client=fake)
    sku_ids = ["NF-DW-001", "NF-DW-003", "NF-DW-004", "NF-DW-002"]

    result = client.review(sku_ids)

    catalog_call = next(
        call for call in result["mcp_trace"] if call["name"] == "get_catalog"
    )
    catalog_records = json.loads(catalog_call["output"])["records"]
    assert catalog_call["arguments"]["sku_ids"] == sku_ids
    assert [record["sku_id"] for record in catalog_records] == sku_ids
    assert {finding["sku_id"] for finding in result["proposal"]["findings"]} == set(
        sku_ids
    )


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


def test_review_rejects_missing_catalog_declared_code() -> None:
    fake = FakeOpenAI()
    fake.responses.catalog_declared_code_override = ""
    client = TariffReviewClient(config=config(), openai_client=fake)

    with pytest.raises(
        ResponseValidationError,
        match="get_catalog returned no declared code for NF-DW-001",
    ):
        client.review(["NF-DW-001"])


def test_catalog_accepts_mcp_structured_list_wrapper() -> None:
    client = TariffReviewClient(config=config(), openai_client=FakeOpenAI())
    sku_ids = ["NF-DW-001", "NF-DW-002"]
    records = Repository().get_catalog("northfield-home-goods", sku_ids)

    declared_codes = client._catalog_declared_codes(
        json.dumps({"result": records}), sku_ids
    )

    assert declared_codes == {
        "NF-DW-001": "9617.00.1000",
        "NF-DW-002": "7323.93.0080",
    }


def test_catalog_accepts_mcp_text_content_blocks() -> None:
    client = TariffReviewClient(config=config(), openai_client=FakeOpenAI())
    sku_ids = ["NF-DW-001", "NF-DW-002"]
    records = Repository().get_catalog("northfield-home-goods", sku_ids)
    payload = {
        "content": [
            {"type": "text", "text": json.dumps(record)} for record in records
        ]
    }

    declared_codes = client._catalog_declared_codes(json.dumps(payload), sku_ids)

    assert list(declared_codes) == sku_ids


def test_catalog_accepts_complete_records_in_a_different_order() -> None:
    client = TariffReviewClient(config=config(), openai_client=FakeOpenAI())
    sku_ids = ["NF-DW-003", "NF-DW-001", "NF-DW-002"]
    records = Repository().get_catalog("northfield-home-goods", sku_ids)

    declared_codes = client._catalog_declared_codes(
        json.dumps({"records": list(reversed(records))}), sku_ids
    )

    assert list(declared_codes) == sku_ids


def test_catalog_rejects_duplicate_records_even_when_coverage_matches() -> None:
    client = TariffReviewClient(config=config(), openai_client=FakeOpenAI())
    sku_ids = ["NF-DW-001", "NF-DW-002"]
    records = Repository().get_catalog("northfield-home-goods", sku_ids)

    with pytest.raises(
        ResponseValidationError, match=r"duplicates=\['NF-DW-001'\]"
    ):
        client._catalog_declared_codes(
            json.dumps({"records": [records[0], records[0], records[1]]}), sku_ids
        )


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
