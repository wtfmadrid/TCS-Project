"""Checks the installed seed data; does not modify the database."""

from datetime import datetime

from database import (
    find_customer, get_customer_orders, get_customer_overview,
    get_customer_tickets, get_ticket_details, read_connection,
)


def check_database():
    with read_connection() as conn:
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("customers", "orders", "support_tickets", "ticket_messages")}
        assert counts["customers"] == 75, counts
        assert counts["orders"] == 200, counts
        assert counts["support_tickets"] == 300, counts
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert not conn.execute("""
            SELECT 1 FROM support_tickets t JOIN orders o ON t.order_id=o.order_id
            WHERE t.customer_id != o.customer_id
        """).fetchall()
        assert not conn.execute("""
            SELECT 1 FROM orders o JOIN customers c ON o.customer_id=c.customer_id
            WHERE o.order_date < c.joined_date
        """).fetchall()
        assert not conn.execute("""
            SELECT 1 FROM support_tickets t JOIN customers c ON t.customer_id=c.customer_id
            LEFT JOIN orders o ON t.order_id=o.order_id
            WHERE substr(t.created_at,1,10) < c.joined_date
               OR substr(t.created_at,1,10) < o.order_date
               OR (t.category IN ('refund','returns') AND o.delivery_date IS NOT NULL
                   AND substr(t.created_at,1,10) < o.delivery_date)
        """).fetchall()
        assert not conn.execute("""
            SELECT 1 FROM ticket_messages m JOIN support_tickets t ON m.ticket_id=t.ticket_id
            WHERE m.sent_at < t.created_at
               OR (t.resolved_at IS NOT NULL AND m.sent_at > t.resolved_at)
        """).fetchall()
        assert not conn.execute("""
            SELECT t.ticket_id FROM support_tickets t LEFT JOIN ticket_messages m
            ON m.ticket_id=t.ticket_id GROUP BY t.ticket_id HAVING COUNT(m.message_id)<2
        """).fetchall()
        # Parse every date/timestamp, not just its lexical ordering.
        for table, columns in {
            "customers": ("joined_date",), "orders": ("order_date", "delivery_date"),
            "support_tickets": ("created_at", "resolved_at"), "ticket_messages": ("sent_at",),
        }.items():
            for row in conn.execute(f"SELECT {','.join(columns)} FROM {table}"):
                for value in row:
                    if value is not None:
                        assert datetime.fromisoformat(value) < datetime(2026, 10, 2)

    for name in ("Ema", "Liam", "Sophia", "Noah", "Priya", "Alex Morgan"):
        assert find_customer(name)["status"] == "ambiguous", name
    assert find_customer("EMA.WILSON@EXAMPLE.COM")["matches"][0]["customer_id"] == 1
    assert find_customer("Nobody Exists")["status"] == "not_found"
    assert find_customer("' OR 1=1 --")["status"] == "not_found"
    assert find_customer("   ")["status"] == "invalid_input"
    assert get_customer_overview(1)["ticket_counts"] == {"open": 1, "pending": 2, "resolved": 1}
    assert get_customer_overview(1)["total_orders"] == 3
    assert get_customer_tickets(1, "open")["tickets"][0]["ticket_id"] == 101
    assert get_customer_tickets(1, "wrong")["status"] == "invalid_input"
    assert get_customer_tickets(5)["count"] == 0
    assert get_customer_orders(5)["count"] == 0
    assert get_customer_tickets(999)["status"] == "not_found"
    assert get_customer_orders(999)["status"] == "not_found"
    assert get_customer_overview(999)["status"] == "not_found"
    assert get_ticket_details(9999)["status"] == "not_found"
    assert get_ticket_details(101)["order"]["order_id"] == 1001
    assert get_ticket_details(107)["order"]["order_id"] == 1001
    assert get_ticket_details(106)["order"]["delivery_date"] is None
    assert get_ticket_details(104)["order"] is None
    assert len(get_ticket_details(101)["messages"]) == 3
    print("All expanded database checks passed.")
    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    check_database()
