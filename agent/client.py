from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from openai import OpenAI

from agent.schema import (
    ClassificationProposal,
    strict_response_format,
    validate_evidence_and_codes,
)
from data.duty import DutyCalculator
from data.repository import PROJECT_ROOT, Repository
from server.approval import ApprovalStore


READ_TOOLS = [
    "get_catalog",
    "get_entries",
    "search_hts",
    "search_rulings",
    "get_ruling",
    "compute_duty_delta",
]
DRAFT_TOOL = "draft_correction"


class LiveConfigurationError(RuntimeError):
    pass


class ResponseValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAIConfig:
    model: str
    server_url: str | None
    tunnel_id: str | None
    authorization: str | None
    input_cost_per_million: Decimal | None
    output_cost_per_million: Decimal | None
    cached_input_cost_per_million: Decimal | None = None
    cache_write_cost_per_million: Decimal | None = None
    pricing_observed_at: str | None = None
    pricing_source_url: str | None = None
    service_tier: str = "default"

    @classmethod
    def from_env(cls) -> "OpenAIConfig":
        if not os.getenv("OPENAI_API_KEY"):
            raise LiveConfigurationError("OPENAI_API_KEY is required for a live run")
        model = os.getenv("OPENAI_MODEL", "").strip()
        if not model:
            raise LiveConfigurationError("OPENAI_MODEL is required for a live run")
        server_url = os.getenv("MCP_SERVER_URL", "").strip() or None
        tunnel_id = os.getenv("MCP_TUNNEL_ID", "").strip() or None
        if bool(server_url) == bool(tunnel_id):
            raise LiveConfigurationError(
                "Set exactly one of MCP_SERVER_URL or MCP_TUNNEL_ID"
            )
        authorization = os.getenv("MCP_AUTH_TOKEN", "").strip() or None
        if server_url and not server_url.startswith("https://"):
            raise LiveConfigurationError(
                "MCP_SERVER_URL must use HTTPS; use MCP_TUNNEL_ID for a local server"
            )
        if server_url and not authorization:
            raise LiveConfigurationError(
                "MCP_AUTH_TOKEN is required with MCP_SERVER_URL; the demo refuses an unauthenticated public endpoint"
            )

        def optional_decimal(name: str) -> Decimal | None:
            value = os.getenv(name, "").strip()
            return Decimal(value) if value else None

        price_names = (
            "OPENAI_INPUT_COST_PER_MILLION",
            "OPENAI_CACHED_INPUT_COST_PER_MILLION",
            "OPENAI_CACHE_WRITE_COST_PER_MILLION",
            "OPENAI_OUTPUT_COST_PER_MILLION",
        )
        explicit_prices = [optional_decimal(name) for name in price_names]
        if any(value is not None for value in explicit_prices) and not all(
            value is not None for value in explicit_prices
        ):
            raise LiveConfigurationError(
                "Set all four OpenAI token-price variables or leave all four blank"
            )

        pricing_observed_at = os.getenv("OPENAI_PRICING_OBSERVED_AT", "").strip() or None
        pricing_source_url = os.getenv("OPENAI_PRICING_SOURCE_URL", "").strip() or None
        if all(value is not None for value in explicit_prices):
            if not pricing_observed_at or not pricing_source_url:
                raise LiveConfigurationError(
                    "Explicit token prices require OPENAI_PRICING_OBSERVED_AT and OPENAI_PRICING_SOURCE_URL"
                )
            input_price, cached_price, write_price, output_price = explicit_prices
        else:
            registry = json.loads(
                (PROJECT_ROOT / "config" / "openai_pricing.json").read_text(
                    encoding="utf-8"
                )
            )
            model_prices = registry["models"].get(model)
            if model_prices:
                input_price = Decimal(model_prices["input"])
                cached_price = Decimal(model_prices["cached_input"])
                write_price = Decimal(model_prices["cache_write"])
                output_price = Decimal(model_prices["output"])
                pricing_observed_at = registry["observed_at"]
                pricing_source_url = registry["source_url"]
            else:
                input_price = cached_price = write_price = output_price = None

        return cls(
            model=model,
            server_url=server_url,
            tunnel_id=tunnel_id,
            authorization=authorization,
            input_cost_per_million=input_price,
            cached_input_cost_per_million=cached_price,
            cache_write_cost_per_million=write_price,
            output_cost_per_million=output_price,
            pricing_observed_at=pricing_observed_at,
            pricing_source_url=pricing_source_url,
            service_tier="default",
        )


@dataclass(frozen=True)
class PendingDraft:
    response_id: str
    approval_request_id: str
    tool_name: str
    arguments: dict[str, Any]
    approval_token: str
    request_execution: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def live_configuration_status() -> tuple[bool, str]:
    try:
        OpenAIConfig.from_env()
    except (LiveConfigurationError, ValueError) as exc:
        return False, str(exc)
    return True, "Live Responses API + remote MCP configuration is present"


class TariffReviewClient:
    def __init__(
        self,
        config: OpenAIConfig | None = None,
        repository: Repository | None = None,
        calculator: DutyCalculator | None = None,
        approval_store: ApprovalStore | None = None,
        openai_client: OpenAI | None = None,
    ) -> None:
        self.config = config or OpenAIConfig.from_env()
        self.repository = repository or Repository()
        self.calculator = calculator or DutyCalculator(self.repository)
        self.approval_store = approval_store or ApprovalStore(
            PROJECT_ROOT / "runs" / "approvals.json"
        )
        self.client = openai_client or OpenAI()
        self.instructions = (PROJECT_ROOT / "agent" / "instructions.md").read_text(
            encoding="utf-8"
        )

    def _mcp_tool(
        self, allowed_tools: list[str], require_approval: str | dict[str, Any]
    ) -> dict[str, Any]:
        tool: dict[str, Any] = {
            "type": "mcp",
            "server_label": "harbor_crane_tariff_review",
            "server_description": (
                "Bounded synthetic catalog, verified tariff evidence, deterministic "
                "base-duty calculator, and approval-gated local correction drafts."
            ),
            "allowed_tools": allowed_tools,
            "require_approval": require_approval,
        }
        if self.config.server_url:
            tool["server_url"] = self.config.server_url
        else:
            tool["tunnel_id"] = self.config.tunnel_id
        if self.config.authorization:
            tool["authorization"] = self.config.authorization
        return tool

    @staticmethod
    def _item_type(item: Any) -> str | None:
        return getattr(item, "type", None) or (
            item.get("type") if isinstance(item, dict) else None
        )

    @staticmethod
    def _item_value(item: Any, name: str) -> Any:
        if isinstance(item, dict):
            return item.get(name)
        return getattr(item, name, None)

    def _validate_response(self, response: Any, expect_text: bool = True) -> None:
        if getattr(response, "status", None) != "completed":
            details = getattr(response, "incomplete_details", None)
            raise ResponseValidationError(
                f"Response did not complete safely: {getattr(response, 'status', None)}; "
                f"details={details}"
            )
        for item in getattr(response, "output", []):
            item_type = self._item_type(item)
            if item_type == "mcp_call" and self._item_value(item, "error"):
                raise ResponseValidationError(
                    f"MCP call failed: {self._item_value(item, 'error')}"
                )
            if item_type == "message":
                for content in self._item_value(item, "content") or []:
                    if self._item_type(content) == "refusal":
                        raise ResponseValidationError(
                            f"Model refused the request: {self._item_value(content, 'refusal')}"
                        )
        if expect_text and not getattr(response, "output_text", "").strip():
            raise ResponseValidationError("Completed response did not contain output text")

    @classmethod
    def _mcp_trace(cls, response: Any) -> list[dict[str, Any]]:
        trace = []
        for item in getattr(response, "output", []):
            if cls._item_type(item) != "mcp_call":
                continue
            arguments = cls._item_value(item, "arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"unparseable": True}
            output = cls._item_value(item, "output")
            if hasattr(output, "model_dump"):
                output = output.model_dump(mode="json")
            trace.append(
                {
                    "name": cls._item_value(item, "name"),
                    "arguments": arguments,
                    "output": output,
                    "error": cls._item_value(item, "error"),
                }
            )
        return trace

    @staticmethod
    def _trace_text(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, default=str)
        except TypeError:
            return str(value)

    def _usage_record(self, response: Any, elapsed: float) -> dict[str, Any]:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        input_details = getattr(usage, "input_tokens_details", None) if usage else None
        output_details = getattr(usage, "output_tokens_details", None) if usage else None
        cached_tokens = (
            getattr(input_details, "cached_tokens", 0) if input_details else 0
        )
        cache_write_tokens = (
            getattr(input_details, "cache_write_tokens", 0) if input_details else 0
        )
        reasoning_tokens = (
            getattr(output_details, "reasoning_tokens", 0) if output_details else 0
        )
        uncached_input_tokens = None
        if input_tokens is not None:
            uncached_input_tokens = input_tokens - cached_tokens - cache_write_tokens
            if uncached_input_tokens < 0:
                raise ResponseValidationError(
                    "Usage details exceed reported input tokens; cost cannot be computed safely"
                )
        cost: Decimal | None = None
        if (
            uncached_input_tokens is not None
            and output_tokens is not None
            and self.config.input_cost_per_million is not None
            and self.config.cached_input_cost_per_million is not None
            and self.config.cache_write_cost_per_million is not None
            and self.config.output_cost_per_million is not None
        ):
            cost = (
                Decimal(uncached_input_tokens) * self.config.input_cost_per_million
                + Decimal(cached_tokens)
                * self.config.cached_input_cost_per_million
                + Decimal(cache_write_tokens)
                * self.config.cache_write_cost_per_million
                + Decimal(output_tokens) * self.config.output_cost_per_million
            ) / Decimal("1000000")
        response_model = getattr(response, "model", self.config.model)
        response_tier = getattr(response, "service_tier", self.config.service_tier)
        return {
            "mode": "live_responses_api_remote_mcp",
            "response_id": getattr(response, "id", None),
            "model": response_model,
            "service_tier": response_tier,
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "api_usage": {
                "input_tokens": input_tokens,
                "uncached_input_tokens": uncached_input_tokens,
                "cached_input_tokens": cached_tokens,
                "cache_write_tokens": cache_write_tokens,
                "output_tokens": output_tokens,
                "reasoning_tokens": reasoning_tokens,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
            },
            "latency_seconds": round(elapsed, 3),
            "api_cost_usd": f"{cost:.6f}" if cost is not None else None,
            "cost_basis": {
                "status": "calculated" if cost is not None else "unavailable",
                "pricing_observed_at": self.config.pricing_observed_at,
                "pricing_source_url": self.config.pricing_source_url,
                "currency": "USD",
                "unit": "per_1m_tokens",
                "context_band": "short_context_up_to_272k_input_tokens",
                "rates": {
                    "input": (
                        str(self.config.input_cost_per_million)
                        if self.config.input_cost_per_million is not None
                        else None
                    ),
                    "cached_input": (
                        str(self.config.cached_input_cost_per_million)
                        if self.config.cached_input_cost_per_million is not None
                        else None
                    ),
                    "cache_write": (
                        str(self.config.cache_write_cost_per_million)
                        if self.config.cache_write_cost_per_million is not None
                        else None
                    ),
                    "output": (
                        str(self.config.output_cost_per_million)
                        if self.config.output_cost_per_million is not None
                        else None
                    ),
                },
                "note": (
                    "Estimated from API-reported token categories at dated published rates; billing records remain authoritative."
                    if cost is not None
                    else "No dated pricing entry exists for the configured model."
                ),
            },
        }

    @classmethod
    def _mcp_inventory(cls, response: Any) -> list[dict[str, Any]]:
        inventories = []
        for item in getattr(response, "output", []):
            if cls._item_type(item) != "mcp_list_tools":
                continue
            tools = cls._item_value(item, "tools") or []
            inventories.append(
                {
                    "server_label": cls._item_value(item, "server_label"),
                    "tool_names": sorted(
                        name
                        for tool in tools
                        if (name := cls._item_value(tool, "name"))
                    ),
                    "error": cls._item_value(item, "error"),
                }
            )
        return inventories

    def review(
        self,
        sku_ids: list[str],
        description_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not sku_ids:
            raise ValueError("Select at least one SKU")
        run_id = f"RUN-{uuid.uuid4().hex[:10].upper()}"
        overrides = description_overrides or {}
        prompt = {
            "task": "Review the selected synthetic SKUs using the MCP evidence tools.",
            "run_id": run_id,
            "client_id": "northfield-home-goods",
            "sku_ids": sku_ids,
            "description_overrides": overrides,
            "required_tool_behavior": [
                (
                    "Fetch every selected product with get_catalog. Pass the exact "
                    "description_overrides object supplied above to get_catalog so "
                    "review-only edits replace the stored descriptions for this run."
                ),
                "Fetch every selected product's entries.",
                "Search the HTS cache and fetch every cited ruling.",
                "Do not call draft_correction during review.",
            ],
        }
        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.config.model,
            service_tier=self.config.service_tier,
            instructions=self.instructions,
            input=json.dumps(prompt),
            tools=[
                self._mcp_tool(
                    READ_TOOLS,
                    {"never": {"tool_names": READ_TOOLS}},
                )
            ],
            text={"format": strict_response_format()},
            store=True,
        )
        elapsed = time.perf_counter() - started
        self._validate_response(response)
        proposal = ClassificationProposal.model_validate_json(response.output_text)
        if proposal.run_id != run_id or proposal.client_id != "northfield-home-goods":
            raise ResponseValidationError("Response run/client identity did not match")
        trace = self._mcp_trace(response)
        if overrides:
            override_catalog_calls = [
                call
                for call in trace
                if call["name"] == "get_catalog"
                and not call["error"]
                and isinstance(call["arguments"], dict)
                and call["arguments"].get("description_overrides") == overrides
            ]
            if not override_catalog_calls:
                raise ResponseValidationError(
                    "Description overrides were not applied through get_catalog"
                )
        fetched_ruling_ids = {
            str(call["arguments"].get("ruling_id", "")).upper()
            for call in trace
            if call["name"] == "get_ruling"
            and isinstance(call["arguments"], dict)
            and not call["error"]
        }
        validate_evidence_and_codes(
            proposal, fetched_ruling_ids, self.repository.hts_codes
        )
        fetched_hts_codes: set[str] = set()
        for call in trace:
            if call["name"] == "search_hts" and not call["error"]:
                fetched_hts_codes.update(
                    re.findall(r"\b\d{4}\.\d{2}\.\d{4}\b", self._trace_text(call["output"]))
                )
        proposed_codes = {
            finding.proposed_code
            for finding in proposal.findings
            if finding.proposed_code is not None
        }
        unfetched_codes = proposed_codes - fetched_hts_codes
        if unfetched_codes:
            raise ResponseValidationError(
                f"Proposal uses HTS codes not returned by search_hts in this run: {sorted(unfetched_codes)}"
            )

        selected = set(sku_ids)
        returned = {finding.sku_id for finding in proposal.findings}
        if returned != selected:
            raise ResponseValidationError(
                f"Response SKU coverage mismatch: expected {sorted(selected)}, got {sorted(returned)}"
            )

        calculations: dict[str, dict[str, Any]] = {}
        for finding in proposal.findings:
            if finding.proposed_code and finding.proposed_code != finding.declared_code:
                result = self.calculator.compute_duty_delta(
                    proposal.client_id,
                    finding.sku_id,
                    finding.declared_code,
                    finding.proposed_code,
                )
                if result["direction"] != finding.outcome:
                    raise ResponseValidationError(
                        f"Outcome/duty direction mismatch for {finding.sku_id}"
                    )
                calculations[finding.sku_id] = result

        overpayment = sum(
            Decimal(item["potential_base_duty_difference"])
            for item in calculations.values()
            if Decimal(item["potential_base_duty_difference"]) > 0
        )
        underpayment = sum(
            -Decimal(item["potential_base_duty_difference"])
            for item in calculations.values()
            if Decimal(item["potential_base_duty_difference"]) < 0
        )
        review = {
            "proposal": proposal.model_dump(mode="json"),
            "calculations": calculations,
            "mcp_trace": trace,
            "remote_mcp": {
                "transport": (
                    "secure_mcp_tunnel" if self.config.tunnel_id else "authenticated_https"
                ),
                "server_label": "harbor_crane_tariff_review",
                "tool_discovery": self._mcp_inventory(response),
                "successful_calls": [
                    call["name"] for call in trace if not call["error"]
                ],
            },
            "structured_output_validated": True,
            "potential_overpayment_total": f"{overpayment:.2f}",
            "potential_underpayment_total": f"{underpayment:.2f}",
            "execution": self._usage_record(response, elapsed),
        }
        destination = PROJECT_ROOT / "runs" / f"{run_id}.json"
        destination.write_text(json.dumps(review, indent=2), encoding="utf-8")
        return review

    def request_draft(self, finding: dict[str, Any]) -> PendingDraft:
        if finding["outcome"] != "potential_overpayment":
            raise ValueError("Only a potential overpayment may enter the broker draft flow")
        context = {
            "client_id": "northfield-home-goods",
            "sku_id": finding["sku_id"],
            "purpose": "single local correction draft",
        }
        token = self.approval_store.create_pending(context)
        intended_arguments = {
            "client_id": "northfield-home-goods",
            "sku_id": finding["sku_id"],
            "declared_code": finding["declared_code"],
            "proposed_code": finding["proposed_code"],
            "evidence_ids": finding["rulings_cited"],
            "rationale": finding["deciding_rule"],
            "route": "broker",
            "approval_token": token,
        }
        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.config.model,
            service_tier=self.config.service_tier,
            instructions=(
                "Call draft_correction exactly once with the exact JSON arguments "
                "provided. Do not change, omit, or add values."
            ),
            input=json.dumps(intended_arguments),
            tools=[self._mcp_tool([DRAFT_TOOL], "always")],
            store=True,
        )
        elapsed = time.perf_counter() - started
        if getattr(response, "status", None) not in {"completed", "incomplete"}:
            self.approval_store.deny(token)
            raise ResponseValidationError("Draft request failed before approval")
        requests = [
            item
            for item in getattr(response, "output", [])
            if self._item_type(item) == "mcp_approval_request"
        ]
        if len(requests) != 1:
            self.approval_store.deny(token)
            raise ResponseValidationError(
                f"Expected one MCP approval request; received {len(requests)}"
            )
        item = requests[0]
        raw_arguments = self._item_value(item, "arguments")
        arguments = (
            json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        )
        if arguments != intended_arguments or self._item_value(item, "name") != DRAFT_TOOL:
            self.approval_store.deny(token)
            raise ResponseValidationError("Pending draft tool name or arguments changed")
        return PendingDraft(
            response_id=response.id,
            approval_request_id=self._item_value(item, "id"),
            tool_name=DRAFT_TOOL,
            arguments=arguments,
            approval_token=token,
            request_execution=self._usage_record(response, elapsed),
        )

    def resolve_draft(self, pending: PendingDraft, approve: bool) -> dict[str, Any]:
        if approve:
            self.approval_store.approve(pending.approval_token, pending.arguments)
        else:
            self.approval_store.deny(pending.approval_token)
        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.config.model,
            service_tier=self.config.service_tier,
            previous_response_id=pending.response_id,
            # A previous response preserves conversation context but does not
            # enable its MCP server for this new approval-continuation request.
            tools=[self._mcp_tool([DRAFT_TOOL], "always")],
            input=[
                {
                    "type": "mcp_approval_response",
                    "approve": approve,
                    "approval_request_id": pending.approval_request_id,
                }
            ],
        )
        elapsed = time.perf_counter() - started
        self._validate_response(response, expect_text=False)
        calls = [
            item
            for item in getattr(response, "output", [])
            if self._item_type(item) == "mcp_call"
        ]
        if not approve:
            return {
                "status": "denied",
                "response_id": response.id,
                "execution": self._usage_record(response, elapsed),
            }
        if len(calls) != 1 or self._item_value(calls[0], "name") != DRAFT_TOOL:
            raise ResponseValidationError("Approved response did not execute one draft call")
        output = self._item_value(calls[0], "output")
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                output = {"raw_output": output}
        return {
            "status": "draft_created",
            "response_id": response.id,
            "output": output,
            "execution": self._usage_record(response, elapsed),
        }
