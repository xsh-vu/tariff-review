import asyncio

from mcp import Client

from server.mcp_server import mcp


def test_in_memory_mcp_discovery_and_calculator_call() -> None:
    async def exercise() -> None:
        async with Client(mcp, raise_exceptions=True) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert {
                "get_catalog",
                "get_entries",
                "search_hts",
                "search_hts_batch",
                "search_rulings",
                "search_rulings_batch",
                "get_ruling",
                "compute_duty_delta",
                "draft_correction",
            } <= names
            result = await client.call_tool(
                "compute_duty_delta",
                {
                    "client_id": "northfield-home-goods",
                    "sku_id": "NF-DW-001",
                    "declared_code": "9617.00.1000",
                    "proposed_code": "7323.93.0080",
                },
            )
            assert result.is_error is False
            assert result.structured_content["potential_base_duty_difference"] == "12480.00"
            entries = await client.call_tool(
                "get_entries",
                {
                    "client_id": "northfield-home-goods",
                    "sku_ids": ["NF-DW-001", "NF-DW-002"],
                },
            )
            assert entries.is_error is False
            assert {item["sku_id"] for item in entries.structured_content["entries"]} == {
                "NF-DW-001",
                "NF-DW-002",
            }
            rulings = await client.call_tool(
                "search_rulings_batch",
                {"queries": ["N321134", "N224817"]},
            )
            assert rulings.is_error is False
            matches = [
                match
                for group in rulings.structured_content["results"]
                for match in group["matches"]
            ]
            assert {match["ruling_id"] for match in matches} == {
                "N321134",
                "N224817",
            }

    asyncio.run(exercise())
