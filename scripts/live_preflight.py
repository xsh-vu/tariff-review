from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from agent.client import TariffReviewClient
from data.repository import PROJECT_ROOT


OUTPUT = PROJECT_ROOT / "runs" / "live_preflight.json"


def run_preflight(output: Path = OUTPUT) -> dict[str, Any]:
    load_dotenv(PROJECT_ROOT / ".env")
    started = time.perf_counter()
    record: dict[str, Any]
    try:
        review = TariffReviewClient().review(["NF-DW-001"])
        finding = review["proposal"]["findings"][0]
        execution = review["execution"]
        discovery = review["remote_mcp"]["tool_discovery"]
        discovered_tools = {
            name
            for inventory in discovery
            for name in inventory.get("tool_names", [])
        }
        successful_calls = set(review["remote_mcp"]["successful_calls"])
        checks = {
            "authenticated_remote_mcp_discovered": bool(discovery)
            and not any(item.get("error") for item in discovery),
            "review_mcp_tool_scope_exact": discovered_tools
            == {
                "get_catalog",
                "get_entries",
                "search_hts",
                "search_rulings",
                "get_ruling",
            },
            "required_mcp_tools_called": {
                "get_catalog",
                "get_entries",
                "search_hts",
                "get_ruling",
            }.issubset(successful_calls),
            "structured_output_validated": review["structured_output_validated"] is True,
            "expected_classification": finding["outcome"] == "potential_overpayment"
            and finding["proposed_code"] == "7323.93.0080",
            "response_metadata_present": bool(execution["response_id"])
            and bool(execution["model"])
            and execution["api_usage"]["total_tokens"] is not None,
            "dated_cost_calculated": execution["api_cost_usd"] is not None
            and bool(execution["cost_basis"]["pricing_observed_at"]),
        }
        record = {
            "status": "passed" if all(checks.values()) else "failed",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "checks": checks,
            "execution": execution,
            "remote_mcp": review["remote_mcp"],
            "finding": {
                "sku_id": finding["sku_id"],
                "outcome": finding["outcome"],
                "proposed_code": finding["proposed_code"],
                "rulings_cited": finding["rulings_cited"],
                "potential_base_duty_difference": review["calculations"][
                    "NF-DW-001"
                ]["potential_base_duty_difference"],
            },
        }
    except Exception as exc:
        record = {
            "status": "failed",
            "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "attempted_configuration": {
                "model": os.getenv("OPENAI_MODEL"),
                "remote_mcp_transport": (
                    "private_tunnel" if os.getenv("MCP_TUNNEL_ID") else "https"
                ),
                "remote_mcp_configured": bool(
                    os.getenv("MCP_TUNNEL_ID") or os.getenv("MCP_SERVER_URL")
                ),
                "structured_output_requested": True,
            },
            "failure": {"type": type(exc).__name__, "message": str(exc)},
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def main() -> None:
    result = run_preflight()
    print(json.dumps(result, indent=2))
    if result["status"] != "passed":
        sys.exit(1)


if __name__ == "__main__":
    main()
