from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from openai import OpenAI

from agent.client import (
    MCP_SERVER_LABEL,
    OpenAIConfig,
    ResponseValidationError,
    TariffReviewClient,
)
from evals.heldout.schema import (
    HistoricalClassification,
    strict_historical_response_format,
)


HISTORICAL_TOOLS = ["search_historical_hts", "search_rulings_batch"]


def _json_safe(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=False, by_alias=True)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class HistoricalCaseClient(TariffReviewClient):
    """Historical eval contract sharing the live client's transport utilities."""

    def __init__(
        self,
        config: OpenAIConfig | None = None,
        openai_client: OpenAI | None = None,
    ) -> None:
        super().__init__(config=config, openai_client=openai_client)
        from data.repository import PROJECT_ROOT

        self.instructions = (
            PROJECT_ROOT / "evals" / "heldout" / "instructions.md"
        ).read_text(encoding="utf-8")
        self._historical_discovery: dict[str, Any] | None = None

    def _historical_mcp_tool(self) -> dict[str, Any]:
        tool: dict[str, Any] = {
            "type": "mcp",
            "server_label": MCP_SERVER_LABEL,
            "server_description": (
                "Read-only, date-bounded USITC HTS evidence and an isolated set of "
                "analogous public CBP rulings for historical classification evals."
            ),
            "allowed_tools": HISTORICAL_TOOLS,
            "require_approval": {"never": {"tool_names": HISTORICAL_TOOLS}},
        }
        if self.config.server_url:
            tool["server_url"] = self.config.server_url
        else:
            tool["tunnel_id"] = self.config.tunnel_id
        if self.config.authorization:
            tool["authorization"] = self.config.authorization
        return tool

    @classmethod
    def _tool_object(cls, value: Any, tool_name: str, depth: int = 0) -> dict[str, Any]:
        if depth > 4:
            raise ResponseValidationError(
                f"{tool_name} returned an excessively nested payload"
            )
        decoded = cls._json_tool_output(value, tool_name)
        if isinstance(decoded, dict):
            if "results" in decoded:
                return decoded
            for key in ("result", "structuredContent", "structured_content"):
                if key in decoded:
                    return cls._tool_object(decoded[key], tool_name, depth + 1)
            if "content" in decoded:
                return cls._tool_object(decoded["content"], tool_name, depth + 1)
        if isinstance(decoded, list) and len(decoded) == 1:
            item = decoded[0]
            if isinstance(item, dict) and item.get("type") == "text":
                item = item.get("text")
            return cls._tool_object(item, tool_name, depth + 1)
        raise ResponseValidationError(f"{tool_name} returned an invalid object")

    @classmethod
    def _validate_discovery(cls, response: Any, discovery_reused: bool) -> None:
        if discovery_reused:
            return
        inventory = cls._mcp_inventory(response)
        if len(inventory) != 1:
            raise ResponseValidationError(
                "Historical eval did not receive one MCP discovery result"
            )
        item = inventory[0]
        if item.get("server_label") != MCP_SERVER_LABEL:
            raise ResponseValidationError(
                "Historical MCP discovery returned the wrong server label"
            )
        if item.get("error"):
            raise ResponseValidationError(
                f"Historical MCP discovery failed: {item['error']}"
            )
        names = item.get("tool_names", [])
        if len(names) != len(set(names)) or set(names) != set(HISTORICAL_TOOLS):
            raise ResponseValidationError(
                "Historical MCP discovery did not match the two-tool allowlist: "
                f"{names}"
            )

    def review_case(self, case: dict[str, Any]) -> dict[str, Any]:
        prompt = {
            "task": "Classify this sanitized historical product case.",
            "case_id": case["case_id"],
            "as_of_date": case["as_of_date"],
            "product_name": case["product_name"],
            "product_facts": case["product_facts"],
            "required_tool_behavior": [
                (
                    "Call search_historical_hts exactly once with as_of_date equal "
                    "to the supplied case date and all necessary HTS queries."
                ),
                (
                    "Call search_rulings_batch exactly once with all queries for "
                    "analogous rulings."
                ),
            ],
        }
        discovery_reused = self._historical_discovery is not None
        serialized_prompt = json.dumps(prompt)
        request_input: str | list[dict[str, Any]]
        if self._historical_discovery is None:
            request_input = serialized_prompt
        else:
            request_input = [
                self._historical_discovery,
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": serialized_prompt}],
                },
            ]

        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.config.model,
            service_tier=self.config.service_tier,
            instructions=self.instructions,
            input=request_input,
            tools=[self._historical_mcp_tool()],
            text={"format": strict_historical_response_format()},
            store=True,
        )
        elapsed = time.perf_counter() - started
        record: dict[str, Any] = {
            "case": {
                "case_id": case["case_id"],
                "as_of_date": case["as_of_date"],
                "product_name": case["product_name"],
                "product_facts": list(case["product_facts"]),
            },
            "request": {
                "model": self.config.model,
                "service_tier": self.config.service_tier,
                "allowed_tools": list(HISTORICAL_TOOLS),
                "structured_output": strict_historical_response_format(),
                "discovery_reused": discovery_reused,
            },
            "response": _json_safe(response),
            "execution": self._usage_record(response, elapsed),
            "status": "response_saved_unvalidated",
        }

        try:
            self._validate_response(response)
            self._validate_discovery(response, discovery_reused)
            proposal = HistoricalClassification.model_validate_json(
                response.output_text
            )
            if proposal.case_id != case["case_id"]:
                raise ResponseValidationError("Response case ID did not match")

            trace = self._mcp_trace(response)
            hts_calls = [
                call
                for call in trace
                if call["name"] == "search_historical_hts" and not call["error"]
            ]
            ruling_calls = [
                call
                for call in trace
                if call["name"] == "search_rulings_batch" and not call["error"]
            ]
            if len(hts_calls) != 1:
                raise ResponseValidationError(
                    "search_historical_hts must be called exactly once"
                )
            if len(ruling_calls) != 1:
                raise ResponseValidationError(
                    "search_rulings_batch must be called exactly once"
                )
            hts_arguments = hts_calls[0]["arguments"]
            if not isinstance(hts_arguments, dict) or hts_arguments.get(
                "as_of_date"
            ) != case["as_of_date"]:
                raise ResponseValidationError(
                    "search_historical_hts used the wrong case date"
                )
            if not isinstance(hts_arguments.get("queries"), list) or not hts_arguments[
                "queries"
            ]:
                raise ResponseValidationError(
                    "search_historical_hts did not include queries"
                )
            ruling_arguments = ruling_calls[0]["arguments"]
            if not isinstance(ruling_arguments, dict) or not isinstance(
                ruling_arguments.get("queries"), list
            ) or not ruling_arguments["queries"]:
                raise ResponseValidationError(
                    "search_rulings_batch did not include queries"
                )

            hts_object = self._tool_object(
                hts_calls[0]["output"], "search_historical_hts"
            )
            if hts_object.get("as_of_date") != case["as_of_date"]:
                raise ResponseValidationError(
                    "Historical HTS result used the wrong case date"
                )
            published_on = date.fromisoformat(hts_object["revision_published_on"])
            if published_on > date.fromisoformat(case["as_of_date"]):
                raise ResponseValidationError(
                    "Historical HTS result used a future revision"
                )
            hts_matches = self._batch_search_matches(
                hts_object, "search_historical_hts"
            )
            ruling_matches = self._batch_search_matches(
                ruling_calls[0]["output"], "search_rulings_batch"
            )
            fetched_codes = {
                str(match.get("code"))
                for match in hts_matches
                if isinstance(match.get("code"), str)
            }
            fetched_hts_ids = {
                str(match.get("evidence_id"))
                for match in hts_matches
                if isinstance(match.get("evidence_id"), str)
            }
            fetched_ruling_ids = {
                str(match.get("ruling_id")).upper()
                for match in ruling_matches
                if isinstance(match.get("ruling_id"), str)
            }
            if proposal.proposed_code and proposal.proposed_code not in fetched_codes:
                raise ResponseValidationError(
                    "Proposed code was not returned by search_historical_hts"
                )
            if set(proposal.hts_evidence_ids) - fetched_hts_ids:
                raise ResponseValidationError("Proposal cites unfetched HTS evidence")
            if {item.upper() for item in proposal.rulings_cited} - fetched_ruling_ids:
                raise ResponseValidationError("Proposal cites unfetched rulings")

            record.update(
                {
                    "status": "validated",
                    "proposal": proposal.model_dump(mode="json"),
                    "mcp": {
                        "expected_tools": list(HISTORICAL_TOOLS),
                        "trace": trace,
                        "fetched_hts_codes": sorted(fetched_codes),
                        "fetched_hts_evidence_ids": sorted(fetched_hts_ids),
                        "fetched_ruling_ids": sorted(fetched_ruling_ids),
                        "revision_id": hts_object["revision_id"],
                        "revision_published_on": hts_object[
                            "revision_published_on"
                        ],
                        "revision_source_url": hts_object["source_url"],
                    },
                }
            )
            discovered = self._reusable_mcp_discovery(response, HISTORICAL_TOOLS)
            if discovered is not None:
                self._historical_discovery = discovered
        except Exception as exc:
            record.update(
                {
                    "status": "failed_validation",
                    "failure": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "mcp": {"trace": self._mcp_trace(response)},
                }
            )
        return record
