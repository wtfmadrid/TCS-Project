import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


BASE_DIR = Path(__file__).resolve().parent


async def call_tool(session, name, arguments):
    result = await session.call_tool(name, arguments=arguments)

    if result.isError:
        raise RuntimeError(f"{name} failed: {result.content}")

    if result.structuredContent is not None:
        return result.structuredContent

    # Compatibility fallback for JSON returned as text.
    for block in result.content:
        if block.type == "text":
            return json.loads(block.text)

    raise RuntimeError(f"{name} returned no usable data")


async def main():
    server = StdioServerParameters(
        # Use the same Python interpreter as this activated environment.
        command=sys.executable,
        args=[str(BASE_DIR / "mcp_server.py")],
        cwd=str(BASE_DIR),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(
            read,
            write,
            read_timeout_seconds=timedelta(seconds=30),
        ) as session:
            await session.initialize()
            print("MCP connection established.")

            response = await session.list_tools()
            tool_names = {tool.name for tool in response.tools}

            expected = {
                "find_customer",
                "get_customer_overview",
                "get_customer_orders",
                "get_customer_tickets",
                "get_ticket_details",
            }

            assert expected.issubset(tool_names), tool_names
            print("All five database tools discovered.")

            matches = await call_tool(
                session, "find_customer", {"name_or_email": "Alex Morgan"}
            )
            assert matches["status"] == "ambiguous"
            assert len(matches["matches"]) == 2
            print("Duplicate-name lookup passed.")

            customer = await call_tool(
                session,
                "find_customer",
                {"name_or_email": "ema.wilson@example.com"},
            )
            assert customer["status"] == "found"
            customer_id = customer["matches"][0]["customer_id"]

            overview = await call_tool(
                session,
                "get_customer_overview",
                {"customer_id": customer_id},
            )
            assert overview["total_tickets"] == 4
            assert overview["total_orders"] == 3
            print("Customer overview passed.")

            orders = await call_tool(
                session,
                "get_customer_orders",
                {"customer_id": customer_id},
            )
            assert orders["count"] == 3
            print("Order retrieval passed.")

            tickets = await call_tool(
                session,
                "get_customer_tickets",
                {"customer_id": customer_id, "status": "open"},
            )
            assert tickets["count"] == 1
            assert tickets["tickets"][0]["ticket_id"] == 101
            print("Filtered ticket retrieval passed.")

            detail = await call_tool(
                session, "get_ticket_details", {"ticket_id": 101}
            )
            assert detail["order"]["order_id"] == 1001
            assert len(detail["messages"]) == 3
            print("Ticket, linked order, and conversation retrieval passed.")

            missing = await call_tool(
                session,
                "get_customer_overview",
                {"customer_id": 999},
            )
            assert missing["status"] == "not_found"
            print("Missing-customer handling passed.")

    print("\nAll MCP checks passed.")


if __name__ == "__main__":
    asyncio.run(main())