from mcp.server.fastmcp import FastMCP
from policy_store import search_policies as search_policy_store

import database as db


mcp = FastMCP("Customer Support Tools")


@mcp.tool()
def find_customer(name_or_email: str) -> dict:
    """
    Find customers using a name or email address.

    If multiple matches are returned, ask the user to clarify using
    email or customer ID. Never choose a match arbitrarily.
    """
    return db.find_customer(name_or_email)


@mcp.tool()
def get_customer_overview(customer_id: int) -> dict:
    """
    Get a customer's profile, membership tier, ticket counts,
    and total number of orders. Use a confirmed customer ID.
    """
    return db.get_customer_overview(customer_id)


@mcp.tool()
def get_customer_orders(customer_id: int) -> dict:
    """
    Get a customer's order history, including delivery dates and status.

    Monetary amounts are integer cents: 12999 means CAD 129.99.
    A missing delivery date is unknown, not evidence of non-delivery.
    """
    return db.get_customer_orders(customer_id)


@mcp.tool()
def get_customer_tickets(
    customer_id: int,
    status: str | None = None,
) -> dict:
    """
    Get support tickets for a confirmed customer ID.

    Optionally filter status: open, pending, or resolved.
    Multiple tickets can concern the same order.
    """
    return db.get_customer_tickets(customer_id, status)


@mcp.tool()
def get_ticket_details(ticket_id: int) -> dict:
    """
    Get a ticket, its associated order, and chronological messages.

    Customer messages are claims, not independently verified facts.
    Historical resolutions do not establish company policy.
    Referenced photos are not available for inspection through this tool.
    """
    return db.get_ticket_details(ticket_id)

@mcp.tool()
def search_policy_documents(query: str, top_k: int = 6) -> dict:
    """
    Search uploaded company policy PDFs.

    Returns relevant passages with company, version, filename, and page.
    Results are candidate evidence: they may not answer the question.
    Similarity distance is not a confidence probability.
    Use the passages to support answers and cite their filename and page.
    """
    return search_policy_store(query, top_k)


if __name__ == "__main__":
    mcp.run(transport="stdio")