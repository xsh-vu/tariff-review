from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from openai import OpenAI

from agent.schema import (
    ClassificationProposal,
    strict_response_format,
    validate_evidence_and_codes,
)
from data.duty import DutyCalculator
from data.repository import PROJECT_ROOT, Repository
from server.approval import ApprovalStore


REVIEW_TOOLS = [
    "get_catalog",
    "get_entries",
    "search_hts_batch",
    "search_rulings_batch",
]
DRAFT_TOOL = "draft_correction"
MCP_SERVER_LABEL = "harbor_crane_tariff_review"
MCP_DISCOVERY_TTL_SECONDS = 1800.0
REVIEW_PROGRESS_HEARTBEAT_SECONDS = 4.0
ProgressCallback = Callable[[str], None]

TOOL_PROGRESS_LABELS = {
    "get_catalog": "retrieved the selected product records",
    "get_entries": "retrieved entry history",
    "search_hts_batch": "searched the verified HTS evidence cache in one batch",
    "search_rulings_batch": "retrieved verified CBP ruling evidence in one batch",
}


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
        self._review_mcp_discovery: dict[str, Any] | None = None
        self._review_mcp_discovery_expires_at = 0.0

    def _mcp_tool(
        self, allowed_tools: list[str], require_approval: str | dict[str, Any]
    ) -> dict[str, Any]:
        tool: dict[str, Any] = {
            "type": "mcp",
            "server_label": MCP_SERVER_LABEL,
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

    @staticmethod
    def _json_tool_output(value: Any, tool_name: str) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError as exc:
                raise ResponseValidationError(
                    f"{tool_name} returned invalid JSON"
                ) from exc
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    @classmethod
    def _record_list_tool_output(
        cls,
        value: Any,
        tool_name: str,
        wrapper_key: str,
        depth: int = 0,
    ) -> list[dict[str, Any]]:
        """Normalize documented JSON and standard MCP structured-content forms."""
        if depth > 4:
            raise ResponseValidationError(
                f"{tool_name} returned an excessively nested payload"
            )
        decoded = cls._json_tool_output(value, tool_name)
        if isinstance(decoded, dict):
            for key in (wrapper_key, "result", "structuredContent", "structured_content"):
                if key in decoded:
                    return cls._record_list_tool_output(
                        decoded[key], tool_name, wrapper_key, depth + 1
                    )
            if "content" in decoded:
                return cls._record_list_tool_output(
                    decoded["content"], tool_name, wrapper_key, depth + 1
                )
        elif isinstance(decoded, list):
            records: list[dict[str, Any]] = []
            for item in decoded:
                if isinstance(item, dict) and item.get("type") == "text":
                    item = item.get("text")
                if isinstance(item, str):
                    item = cls._json_tool_output(item, tool_name)
                if isinstance(item, list):
                    if not all(isinstance(record, dict) for record in item):
                        break
                    records.extend(item)
                    continue
                if not isinstance(item, dict):
                    break
                records.append(item)
            else:
                return records

        if isinstance(decoded, dict):
            shape = f"object keys={sorted(str(key) for key in decoded)}"
        elif isinstance(decoded, list):
            item_types = sorted({type(item).__name__ for item in decoded})
            shape = f"array item_types={item_types}"
        else:
            shape = type(decoded).__name__
        raise ResponseValidationError(
            f"{tool_name} returned an invalid record list ({shape})"
        )

    def _catalog_declared_codes(
        self, catalog_output: Any, sku_ids: list[str]
    ) -> dict[str, str]:
        records = self._record_list_tool_output(
            catalog_output, "get_catalog", "records"
        )
        returned_skus = [record.get("sku_id") for record in records]
        duplicate_skus = sorted(
            {
                str(sku_id)
                for sku_id in returned_skus
                if returned_skus.count(sku_id) > 1
            }
        )
        missing_skus = sorted(set(sku_ids) - set(returned_skus))
        unexpected_skus = sorted(set(returned_skus) - set(sku_ids), key=str)
        if duplicate_skus or missing_skus or unexpected_skus:
            raise ResponseValidationError(
                "get_catalog result did not match the selected SKU batch: "
                f"missing={missing_skus}, unexpected={unexpected_skus}, "
                f"duplicates={duplicate_skus}"
            )
        declared_codes_by_sku: dict[str, str] = {}
        for record in records:
            sku_id = record["sku_id"]
            if record.get("client_id") != "northfield-home-goods":
                raise ResponseValidationError(
                    f"get_catalog returned the wrong client for {sku_id}"
                )
            declared_code = record.get("declared_code")
            if not isinstance(declared_code, str) or not declared_code.strip():
                raise ResponseValidationError(
                    f"get_catalog returned no declared code for {sku_id}"
                )
            declared_code = declared_code.strip()
            if declared_code not in self.repository.hts_codes:
                raise ResponseValidationError(
                    f"get_catalog returned an unsupported declared code for {sku_id}: "
                    f"{declared_code}"
                )
            expected = self.repository.get_product(
                "northfield-home-goods", sku_id
            )["declared_code"]
            if declared_code != expected:
                raise ResponseValidationError(
                    f"get_catalog declared code did not match the application record "
                    f"for {sku_id}"
                )
            declared_codes_by_sku[sku_id] = declared_code
        return {sku_id: declared_codes_by_sku[sku_id] for sku_id in sku_ids}

    @classmethod
    def _batch_search_matches(
        cls, output: Any, tool_name: str
    ) -> list[dict[str, Any]]:
        groups = cls._record_list_tool_output(output, tool_name, "results")
        matches: list[dict[str, Any]] = []
        for group in groups:
            query = group.get("query")
            group_matches = group.get("matches")
            if not isinstance(query, str) or not query.strip():
                raise ResponseValidationError(
                    f"{tool_name} returned a result without its source query"
                )
            if not isinstance(group_matches, list) or not all(
                isinstance(match, dict) for match in group_matches
            ):
                raise ResponseValidationError(
                    f"{tool_name} returned invalid matches for query {query!r}"
                )
            matches.extend(group_matches)
        return matches

    def _usage_record(
        self,
        response: Any,
        elapsed: float,
        latency_breakdown: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
            "latency_breakdown": latency_breakdown,
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

    @classmethod
    def _validate_review_discovery(cls, response: Any) -> None:
        """Fail early when a running MCP process exposes an outdated tool policy."""
        inventories = cls._mcp_inventory(response)
        if not inventories:
            return
        expected = set(REVIEW_TOOLS)
        for inventory in inventories:
            if inventory["server_label"] != MCP_SERVER_LABEL:
                raise ResponseValidationError(
                    "Remote MCP tool discovery returned the wrong server label"
                )
            if inventory["error"]:
                raise ResponseValidationError(
                    f"Remote MCP tool discovery failed: {inventory['error']}"
                )
            discovered = set(inventory["tool_names"])
            if discovered != expected:
                missing = sorted(expected - discovered)
                unexpected = sorted(discovered - expected)
                raise ResponseValidationError(
                    "Remote MCP server exposes a stale or incomplete review tool "
                    f"policy: missing={missing}, unexpected={unexpected}. Restart "
                    "the local MCP server so it advertises the current batch tools, "
                    "then rerun the review."
                )

    @classmethod
    def _reusable_mcp_discovery(
        cls, response: Any, expected_tools: list[str]
    ) -> dict[str, Any] | None:
        """Return a safe, schema-only discovery item for a matching tool policy."""
        for item in getattr(response, "output", []):
            if cls._item_type(item) != "mcp_list_tools":
                continue
            if cls._item_value(item, "error"):
                continue
            if cls._item_value(item, "server_label") != MCP_SERVER_LABEL:
                continue
            item_id = cls._item_value(item, "id")
            tools = cls._item_value(item, "tools") or []
            serialized_tools = []
            for tool in tools:
                name = cls._item_value(tool, "name")
                input_schema = cls._item_value(tool, "input_schema")
                if hasattr(input_schema, "model_dump"):
                    input_schema = input_schema.model_dump(
                        mode="json", exclude_none=True, by_alias=True
                    )
                if not name or not isinstance(input_schema, dict):
                    serialized_tools = []
                    break
                serialized = {"name": name, "input_schema": input_schema}
                for optional in ("annotations", "description"):
                    value = cls._item_value(tool, optional)
                    if hasattr(value, "model_dump"):
                        value = value.model_dump(
                            mode="json", exclude_none=True, by_alias=True
                        )
                    if value is not None:
                        serialized[optional] = value
                serialized_tools.append(serialized)
            names = [tool["name"] for tool in serialized_tools]
            if (
                not item_id
                or len(names) != len(set(names))
                or set(names) != set(expected_tools)
            ):
                continue
            return {
                "id": item_id,
                "type": "mcp_list_tools",
                "server_label": MCP_SERVER_LABEL,
                "tools": serialized_tools,
            }
        return None

    def _current_review_discovery(self) -> dict[str, Any] | None:
        if time.monotonic() >= self._review_mcp_discovery_expires_at:
            self._clear_review_discovery()
        return self._review_mcp_discovery

    def _review_discovery_identity(self) -> dict[str, Any]:
        return {
            "version": 1,
            "server_label": MCP_SERVER_LABEL,
            "transport": "tunnel" if self.config.tunnel_id else "https",
            "endpoint": self.config.tunnel_id or self.config.server_url,
            "allowed_tools": list(REVIEW_TOOLS),
        }

    @staticmethod
    def _valid_cached_discovery(discovery: Any) -> bool:
        if not isinstance(discovery, dict):
            return False
        if discovery.get("type") != "mcp_list_tools":
            return False
        if discovery.get("server_label") != MCP_SERVER_LABEL:
            return False
        if not isinstance(discovery.get("id"), str) or not discovery["id"]:
            return False
        tools = discovery.get("tools")
        if not isinstance(tools, list):
            return False
        names = []
        for tool in tools:
            if not isinstance(tool, dict):
                return False
            name = tool.get("name")
            if not isinstance(name, str) or not isinstance(
                tool.get("input_schema"), dict
            ):
                return False
            names.append(name)
        return len(names) == len(set(names)) and set(names) == set(REVIEW_TOOLS)

    def export_review_discovery_cache(self) -> dict[str, Any] | None:
        discovery = self._current_review_discovery()
        if discovery is None:
            return None
        remaining = self._review_mcp_discovery_expires_at - time.monotonic()
        if remaining <= 0:
            return None
        return {
            **self._review_discovery_identity(),
            "expires_at_epoch": time.time() + remaining,
            "discovery": json.loads(json.dumps(discovery)),
        }

    def restore_review_discovery_cache(self, state: Any) -> bool:
        self._clear_review_discovery()
        if not isinstance(state, dict):
            return False
        identity = self._review_discovery_identity()
        if any(state.get(key) != value for key, value in identity.items()):
            return False
        expires_at = state.get("expires_at_epoch")
        if not isinstance(expires_at, (int, float)):
            return False
        remaining = float(expires_at) - time.time()
        discovery = state.get("discovery")
        if remaining <= 0 or not self._valid_cached_discovery(discovery):
            return False
        self._review_mcp_discovery = json.loads(json.dumps(discovery))
        self._review_mcp_discovery_expires_at = time.monotonic() + min(
            remaining, MCP_DISCOVERY_TTL_SECONDS
        )
        return True

    def _clear_review_discovery(self) -> None:
        self._review_mcp_discovery = None
        self._review_mcp_discovery_expires_at = 0.0

    @staticmethod
    def _review_input(
        prompt: dict[str, Any], discovery: dict[str, Any] | None
    ) -> str | list[dict[str, Any]]:
        serialized_prompt = json.dumps(prompt)
        if discovery is None:
            return serialized_prompt
        return [
            discovery,
            {
                "role": "user",
                "content": [{"type": "input_text", "text": serialized_prompt}],
            },
        ]

    @staticmethod
    def _argument_summary(arguments: Any) -> str:
        if not isinstance(arguments, str) or not arguments:
            return "arguments received"
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return "arguments received"
        if not isinstance(parsed, dict):
            return "arguments received"
        keys = ", ".join(sorted(str(key) for key in parsed))
        return f"arguments ready ({keys})" if keys else "arguments ready"

    def _stream_review_response(
        self,
        request: dict[str, Any],
        report: ProgressCallback,
    ) -> tuple[Any, dict[str, Any]]:
        """Consume Responses API SSE events while keeping UI updates on its thread."""
        event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        wall_started = time.time()
        started = time.perf_counter()

        def consume() -> None:
            try:
                stream = self.client.responses.create(stream=True, **request)
                for event in stream:
                    event_queue.put(("event", event))
            except Exception as exc:
                event_queue.put(("error", exc))
            finally:
                event_queue.put(("done", None))

        worker = threading.Thread(
            target=consume,
            name="tariff-review-response-stream",
            daemon=True,
        )
        worker.start()

        final_response: Any | None = None
        item_names: dict[str, str] = {}
        selected_at: dict[str, float] = {}
        remote_call_started_at: dict[str, float] = {}
        discovery_started_at: float | None = None
        output_started_at: float | None = None
        timeline: list[dict[str, Any]] = []
        segments: list[dict[str, Any]] = []
        reported: set[tuple[str, str]] = set()

        def elapsed() -> float:
            return round(time.perf_counter() - started, 3)

        def record_event(
            event_type: str | None,
            *,
            item_id: str | None = None,
            tool: str | None = None,
            status: str | None = None,
        ) -> float:
            observed_at = elapsed()
            event = {
                "event": event_type or "unknown",
                "at_seconds": observed_at,
            }
            if item_id:
                event["item_id"] = item_id
            if tool:
                event["tool"] = tool
            if status:
                event["status"] = status
            timeline.append(event)
            return observed_at

        def finish_segment(
            phase: str,
            started_at: float | None,
            completed_at: float,
            *,
            status: str,
            tool: str | None = None,
        ) -> None:
            if started_at is None:
                return
            segment = {
                "phase": phase,
                "started_at_seconds": started_at,
                "completed_at_seconds": completed_at,
                "duration_seconds": round(max(0.0, completed_at - started_at), 3),
                "status": status,
            }
            if tool:
                segment["tool"] = tool
            segments.append(segment)

        def report_once(stage: str, item_id: str, message: str) -> None:
            key = (stage, item_id)
            if key not in reported:
                reported.add(key)
                report(message)

        while True:
            try:
                kind, payload = event_queue.get(
                    timeout=REVIEW_PROGRESS_HEARTBEAT_SECONDS
                )
            except queue.Empty:
                elapsed_seconds = int(time.perf_counter() - started)
                report(
                    f"Still working · {elapsed_seconds}s elapsed · waiting for the next "
                    "streamed Responses API or MCP event; no timeout has been reported."
                )
                continue

            if kind == "error":
                raise payload
            if kind == "done":
                break

            event_type = self._item_type(payload)
            item_id = str(self._item_value(payload, "item_id") or "")
            if event_type == "response.created":
                record_event(event_type)
                report_once(
                    "response_created",
                    "response",
                    "Responses API · streaming connection established; the request "
                    "was accepted.",
                )
            elif event_type == "response.in_progress":
                record_event(event_type)
                report_once(
                    "response_in_progress",
                    "response",
                    "Model · reviewing the selected products and deciding which "
                    "allowlisted evidence tools to use.",
                )
            elif event_type == "response.mcp_list_tools.in_progress":
                discovery_started_at = record_event(event_type, item_id=item_id)
                report_once(
                    "discovery_started",
                    item_id,
                    "MCP · connecting to the remote server and importing the "
                    "allowlisted tool definitions.",
                )
            elif event_type == "response.mcp_list_tools.completed":
                completed_at = record_event(
                    event_type, item_id=item_id, status="completed"
                )
                finish_segment(
                    "MCP tool discovery",
                    discovery_started_at,
                    completed_at,
                    status="completed",
                )
                report_once(
                    "discovery_completed",
                    item_id,
                    "MCP · remote connection succeeded; tool discovery completed.",
                )
            elif event_type == "response.mcp_list_tools.failed":
                completed_at = record_event(
                    event_type, item_id=item_id, status="failed"
                )
                finish_segment(
                    "MCP tool discovery",
                    discovery_started_at,
                    completed_at,
                    status="failed",
                )
                report_once(
                    "discovery_failed",
                    item_id,
                    "MCP · tool discovery failed; waiting for the API failure details.",
                )
            elif event_type == "response.output_item.added":
                output_item = self._item_value(payload, "item")
                if self._item_type(output_item) == "mcp_call":
                    output_item_id = str(self._item_value(output_item, "id") or item_id)
                    name = str(self._item_value(output_item, "name") or "MCP tool")
                    item_names[output_item_id] = name
                    selected_at[output_item_id] = record_event(
                        event_type, item_id=output_item_id, tool=name
                    )
                    report_once(
                        "tool_selected",
                        output_item_id,
                        f"MCP · {name} · selected by the model; preparing the call.",
                    )
                elif self._item_type(output_item) == "message":
                    output_started_at = record_event(
                        event_type, status="structured_output_started"
                    )
                    report_once(
                        "message_started",
                        "response",
                        "Structured output · composing the cited classification findings.",
                    )
            elif event_type == "response.mcp_call_arguments.done":
                name = item_names.get(item_id, "MCP tool")
                record_event(event_type, item_id=item_id, tool=name)
                report_once(
                    "arguments_done",
                    item_id,
                    f"MCP · {name} · "
                    f"{self._argument_summary(self._item_value(payload, 'arguments'))}.",
                )
            elif event_type == "response.mcp_call.in_progress":
                name = item_names.get(item_id, "MCP tool")
                remote_call_started_at[item_id] = record_event(
                    event_type, item_id=item_id, tool=name, status="in_progress"
                )
                report_once(
                    "tool_started",
                    item_id,
                    f"MCP · {name} · call in progress on the remote server.",
                )
            elif event_type == "response.mcp_call.completed":
                name = item_names.get(item_id, "MCP tool")
                completed_at = record_event(
                    event_type, item_id=item_id, tool=name, status="completed"
                )
                finish_segment(
                    "MCP tool call",
                    remote_call_started_at.get(item_id, selected_at.get(item_id)),
                    completed_at,
                    status="completed",
                    tool=name,
                )
                action = TOOL_PROGRESS_LABELS.get(name, "tool result returned")
                report_once(
                    "tool_completed",
                    item_id,
                    f"MCP · {name} · completed; {action}.",
                )
            elif event_type == "response.mcp_call.failed":
                name = item_names.get(item_id, "MCP tool")
                completed_at = record_event(
                    event_type, item_id=item_id, tool=name, status="failed"
                )
                finish_segment(
                    "MCP tool call",
                    remote_call_started_at.get(item_id, selected_at.get(item_id)),
                    completed_at,
                    status="failed",
                    tool=name,
                )
                report_once(
                    "tool_failed",
                    item_id,
                    f"MCP · {name} · failed; waiting for the API error details.",
                )
            elif event_type == "response.output_text.done":
                completed_at = record_event(
                    event_type, status="structured_output_completed"
                )
                finish_segment(
                    "Structured output generation",
                    output_started_at,
                    completed_at,
                    status="completed",
                )
                report_once(
                    "output_done",
                    "response",
                    "Structured output · generation finished; finalizing the response.",
                )
            elif event_type in {
                "response.completed",
                "response.failed",
                "response.incomplete",
            }:
                final_response = self._item_value(payload, "response")
                state = event_type.removeprefix("response.")
                record_event(event_type, status=state)
                report_once(
                    "response_terminal",
                    "response",
                    f"Responses API · stream finished with status {state}; validating "
                    "the returned evidence and output.",
                )
            elif event_type == "error":
                message = self._item_value(payload, "message") or "unknown stream error"
                record_event(event_type, status="failed")
                raise ResponseValidationError(f"Responses API stream error: {message}")

        if final_response is None:
            raise ResponseValidationError(
                "Responses API stream ended without a terminal response event"
            )
        breakdown = {
            "started_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(wall_started)
            ),
            "total_stream_seconds": elapsed(),
            "segments": sorted(
                segments, key=lambda segment: segment["started_at_seconds"]
            ),
            "event_timeline": timeline,
            "note": (
                "Timings are observed by the application from streamed lifecycle "
                "events. Segments may overlap and should not be summed."
            ),
        }
        return final_response, breakdown

    def review(
        self,
        sku_ids: list[str],
        description_overrides: dict[str, str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        def report(message: str) -> None:
            if progress_callback is not None:
                progress_callback(message)

        if not sku_ids:
            raise ValueError("Select at least one SKU")
        report(
            f"Preparing a structured tariff-review request for {len(sku_ids)} "
            f"selected SKU{'s' if len(sku_ids) != 1 else ''}."
        )
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
                    "Call get_catalog exactly once with client_id, the complete sku_ids "
                    "array above in the same order, and the exact description_overrides "
                    "object above."
                ),
                (
                    "Call get_entries exactly once with client_id and the complete "
                    "sku_ids array above in the same order."
                ),
                (
                    "Call search_hts_batch exactly once with all HTS queries needed "
                    "for the selected products."
                ),
                (
                    "Call search_rulings_batch exactly once with all ruling queries "
                    "needed for the selected products. Its matches are the complete "
                    "ruling records used for citations."
                ),
                "Do not call draft_correction during review.",
            ],
        }
        reusable_discovery = self._current_review_discovery()
        discovery_reused = reusable_discovery is not None
        transport = (
            "Secure MCP Tunnel" if self.config.tunnel_id else "authenticated HTTPS"
        )
        report(
            "Responses API · opening a streamed review with four allowlisted MCP "
            "tools for product, entry, HTS, and ruling evidence."
        )
        if discovery_reused:
            report(
                "MCP · reusing recent validated tool discovery for the same "
                "four-tool review policy."
            )
        else:
            report(
                f"MCP · requesting a connection through {transport}; waiting for "
                "the server's tool-discovery event."
            )
        started = time.perf_counter()
        response, latency_breakdown = self._stream_review_response(
            {
                "model": self.config.model,
                "service_tier": self.config.service_tier,
                "instructions": self.instructions,
                "input": self._review_input(prompt, reusable_discovery),
                "tools": [
                    self._mcp_tool(
                        REVIEW_TOOLS,
                        {"never": {"tool_names": REVIEW_TOOLS}},
                    )
                ],
                "text": {"format": strict_response_format()},
                "store": True,
            },
            report,
        )
        elapsed = time.perf_counter() - started
        latency_breakdown["mcp_discovery_reused"] = discovery_reused
        try:
            self._validate_response(response)
            self._validate_review_discovery(response)
        except Exception:
            self._clear_review_discovery()
            raise
        discovered = self._reusable_mcp_discovery(response, REVIEW_TOOLS)
        if discovered is not None:
            self._review_mcp_discovery = discovered
            self._review_mcp_discovery_expires_at = (
                time.monotonic() + MCP_DISCOVERY_TTL_SECONDS
            )
        elif any(
            self._item_type(item) == "mcp_list_tools"
            for item in getattr(response, "output", [])
        ):
            self._clear_review_discovery()
        proposal = ClassificationProposal.model_validate_json(response.output_text)
        if proposal.run_id != run_id or proposal.client_id != "northfield-home-goods":
            raise ResponseValidationError("Response run/client identity did not match")
        trace = self._mcp_trace(response)
        report(
            "Validation · checking the strict output schema, selected-SKU coverage, "
            "and fetched citation/HTS provenance."
        )
        catalog_calls = [
            call for call in trace if call["name"] == "get_catalog" and not call["error"]
        ]
        if len(catalog_calls) != 1 or catalog_calls[0]["arguments"] != {
            "client_id": "northfield-home-goods",
            "sku_ids": sku_ids,
            "description_overrides": overrides,
        }:
            raise ResponseValidationError(
                "get_catalog must be called exactly once with the complete SKU batch "
                "and exact description overrides"
            )
        declared_codes = self._catalog_declared_codes(
            catalog_calls[0]["output"], sku_ids
        )
        entry_calls = [
            call for call in trace if call["name"] == "get_entries" and not call["error"]
        ]
        if len(entry_calls) != 1 or entry_calls[0]["arguments"] != {
            "client_id": "northfield-home-goods",
            "sku_ids": sku_ids,
        }:
            raise ResponseValidationError(
                "get_entries must be called exactly once with the complete SKU batch"
            )
        hts_calls = [
            call
            for call in trace
            if call["name"] == "search_hts_batch" and not call["error"]
        ]
        if len(hts_calls) != 1:
            raise ResponseValidationError(
                "search_hts_batch must be called exactly once during review"
            )
        ruling_calls = [
            call
            for call in trace
            if call["name"] == "search_rulings_batch" and not call["error"]
        ]
        if len(ruling_calls) != 1:
            raise ResponseValidationError(
                "search_rulings_batch must be called exactly once during review"
            )
        fetched_hts_matches = self._batch_search_matches(
            hts_calls[0]["output"], "search_hts_batch"
        )
        fetched_ruling_matches = self._batch_search_matches(
            ruling_calls[0]["output"], "search_rulings_batch"
        )
        fetched_ruling_ids = {
            str(record.get("ruling_id", "")).upper()
            for record in fetched_ruling_matches
            if isinstance(record.get("ruling_id"), str)
        }
        validate_evidence_and_codes(
            proposal, fetched_ruling_ids, self.repository.hts_codes
        )
        fetched_hts_codes = {
            code
            for record in fetched_hts_matches
            for code in re.findall(
                r"\b\d{4}\.\d{2}\.\d{4}\b", self._trace_text(record)
            )
        }
        proposed_codes = {
            finding.proposed_code
            for finding in proposal.findings
            if finding.proposed_code is not None
        }
        unfetched_codes = proposed_codes - fetched_hts_codes
        if unfetched_codes:
            raise ResponseValidationError(
                "Proposal uses HTS codes not returned by search_hts_batch in this "
                f"run: {sorted(unfetched_codes)}"
            )

        selected = set(sku_ids)
        returned_ids = [finding.sku_id for finding in proposal.findings]
        returned = set(returned_ids)
        if returned != selected or len(returned_ids) != len(selected):
            raise ResponseValidationError(
                f"Response SKU coverage mismatch: expected {sorted(selected)}, got {sorted(returned)}"
            )

        calculations: dict[str, dict[str, Any]] = {}
        for finding in proposal.findings:
            declared_code = declared_codes[finding.sku_id]
            if finding.proposed_code == declared_code:
                if finding.outcome != "confirmed":
                    raise ResponseValidationError(
                        f"Unchanged classification for {finding.sku_id} must be confirmed"
                    )
                continue
            if finding.outcome == "confirmed":
                raise ResponseValidationError(
                    f"Confirmed finding for {finding.sku_id} changed the tariff code"
                )
            if finding.proposed_code:
                report(
                    f"Application · DutyCalculator.compute_duty_delta · calculating "
                    f"the base-duty difference for {finding.sku_id}."
                )
                result = self.calculator.compute_duty_delta(
                    proposal.client_id,
                    finding.sku_id,
                    declared_code,
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
        discovery_inventory = self._mcp_inventory(response)
        if not discovery_inventory and reusable_discovery is not None:
            discovery_inventory = [
                {
                    "server_label": reusable_discovery["server_label"],
                    "tool_names": sorted(
                        tool["name"] for tool in reusable_discovery["tools"]
                    ),
                    "error": None,
                }
            ]
        proposal_payload = proposal.model_dump(mode="json")
        proposal_payload["status"] = (
            "incomplete"
            if any(
                finding["outcome"] == "needs_info"
                for finding in proposal_payload["findings"]
            )
            else "complete"
        )
        for finding in proposal_payload["findings"]:
            finding["declared_code"] = declared_codes[finding["sku_id"]]
        review = {
            "proposal": proposal_payload,
            "review_scope": {
                "source_revision": self.repository.source_revision,
                "duty_scope": "Column 1 General base duty only",
                "warnings": [
                    "Potential duty differences are not guaranteed refunds.",
                    "Chapter 99 duties, trade remedies, preference programs, and recovery eligibility are excluded.",
                ],
            },
            "calculations": calculations,
            "mcp_trace": trace,
            "remote_mcp": {
                "transport": (
                    "secure_mcp_tunnel" if self.config.tunnel_id else "authenticated_https"
                ),
                "server_label": MCP_SERVER_LABEL,
                "tool_discovery": discovery_inventory,
                "tool_discovery_reused": discovery_reused,
                "successful_calls": [
                    call["name"] for call in trace if not call["error"]
                ],
            },
            "structured_output_validated": True,
            "potential_overpayment_total": f"{overpayment:.2f}",
            "potential_underpayment_total": f"{underpayment:.2f}",
            "execution": self._usage_record(response, elapsed, latency_breakdown),
        }
        report("Audit record · saving the validated proposal, MCP trace, and calculations.")
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
