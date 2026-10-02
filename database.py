"""SQLite storage and read-only tools for the support assistant (Python 3.10+)."""

import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "customers.db"
SCHEMA_VERSION = 2


def initialize_database(path=None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='customers'"
        ).fetchone()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if existing and version != SCHEMA_VERSION:
            raise RuntimeError("Old schema detected. Run: python seed_db.py --reset")
        if existing:
            return
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                customer_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                account_status TEXT NOT NULL CHECK(account_status IN ('active','inactive')),
                membership_tier TEXT NOT NULL CHECK(membership_tier IN ('standard','premium')),
                joined_date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
                product_name TEXT NOT NULL,
                product_category TEXT NOT NULL,
                order_date TEXT NOT NULL,
                delivery_date TEXT,
                amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
                currency TEXT NOT NULL DEFAULT 'CAD' CHECK(currency = 'CAD'),
                status TEXT NOT NULL CHECK(status IN ('processing','shipped','delivered','cancelled','returned')),
                UNIQUE(order_id, customer_id),
                CHECK(delivery_date IS NULL OR delivery_date >= order_date),
                CHECK(delivery_date IS NULL OR status IN ('delivered','returned'))
            );
            CREATE TABLE IF NOT EXISTS support_tickets (
                ticket_id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
                order_id INTEGER,
                subject TEXT NOT NULL,
                category TEXT NOT NULL CHECK(category IN ('refund','returns','shipping','billing','account')),
                priority TEXT NOT NULL CHECK(priority IN ('low','normal','high')),
                status TEXT NOT NULL CHECK(status IN ('open','pending','resolved')),
                created_at TEXT NOT NULL,
                description TEXT NOT NULL,
                resolution TEXT,
                resolved_at TEXT,
                FOREIGN KEY(order_id, customer_id) REFERENCES orders(order_id, customer_id),
                CHECK((status = 'resolved' AND resolution IS NOT NULL AND resolved_at IS NOT NULL)
                   OR (status != 'resolved' AND resolution IS NULL AND resolved_at IS NULL)),
                CHECK(resolved_at IS NULL OR resolved_at >= created_at)
            );
            CREATE TABLE IF NOT EXISTS ticket_messages (
                message_id INTEGER PRIMARY KEY,
                ticket_id INTEGER NOT NULL REFERENCES support_tickets(ticket_id),
                sender_role TEXT NOT NULL CHECK(sender_role IN ('customer','support')),
                sent_at TEXT NOT NULL,
                message TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_customer ON support_tickets(customer_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_order ON support_tickets(order_id);
            CREATE INDEX IF NOT EXISTS idx_messages_ticket ON ticket_messages(ticket_id, sent_at);
            PRAGMA user_version = 2;
        """)


@contextmanager
def read_connection():
    if not DB_PATH.exists():
        raise FileNotFoundError("Database missing. Run: python seed_db.py")
    conn = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise RuntimeError("Old schema detected. Run: python seed_db.py --reset")
        yield conn
    finally:
        conn.close()


def find_customer(name_or_email: str) -> dict:
    """Return all name matches; never choose between ambiguous customers automatically."""
    search = name_or_email.strip()
    if not search:
        return {"status": "invalid_input", "message": "Enter a name or email."}
    with read_connection() as conn:
        rows = conn.execute(
            """SELECT customer_id, name, email, account_status
               FROM customers WHERE lower(email) = lower(?)
               OR instr(lower(name), lower(?)) > 0 ORDER BY customer_id""",
            (search, search),
        ).fetchall()
    matches = [dict(row) for row in rows]
    return {
        "status": "not_found" if not matches else "found" if len(matches) == 1 else "ambiguous",
        "matches": matches,
    }


def get_customer_overview(customer_id: int) -> dict:
    with read_connection() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        if customer is None:
            return {"status": "not_found", "customer_id": customer_id}
        counts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM support_tickets WHERE customer_id = ? GROUP BY status",
            (customer_id,),
        ).fetchall()
        orders = conn.execute("SELECT COUNT(*) FROM orders WHERE customer_id = ?", (customer_id,)).fetchone()[0]
    ticket_counts = {"open": 0, "pending": 0, "resolved": 0}
    ticket_counts.update({row["status"]: row["count"] for row in counts})
    return {"status": "found", "customer": dict(customer), "ticket_counts": ticket_counts,
            "total_tickets": sum(ticket_counts.values()), "total_orders": orders}


def get_customer_orders(customer_id: int) -> dict:
    """Amounts are integer cents in the stated currency, not floating point dollars."""
    with read_connection() as conn:
        if conn.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is None:
            return {"status": "not_found", "customer_id": customer_id}
        rows = conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? ORDER BY order_date DESC, order_id DESC",
            (customer_id,),
        ).fetchall()
    return {"status": "success", "customer_id": customer_id, "count": len(rows), "orders": [dict(r) for r in rows]}


def get_customer_tickets(customer_id: int, status: str | None = None) -> dict:
    if status is not None:
        status = status.strip().lower()
        if status not in {"open", "pending", "resolved"}:
            return {"status": "invalid_input", "message": "Status must be open, pending, or resolved."}
    with read_connection() as conn:
        if conn.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is None:
            return {"status": "not_found", "customer_id": customer_id}
        query = "SELECT * FROM support_tickets WHERE customer_id = ?"
        params = [customer_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        rows = conn.execute(query + " ORDER BY created_at DESC, ticket_id DESC", params).fetchall()
    return {"status": "success", "customer_id": customer_id, "count": len(rows), "tickets": [dict(r) for r in rows]}


def get_ticket_details(ticket_id: int) -> dict:
    """Retrieve the ticket, its linked order, and the chronological conversation."""
    with read_connection() as conn:
        ticket = conn.execute("SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if ticket is None:
            return {"status": "not_found", "ticket_id": ticket_id}
        order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (ticket["order_id"],)).fetchone()
        messages = conn.execute(
            "SELECT * FROM ticket_messages WHERE ticket_id = ? ORDER BY sent_at, message_id", (ticket_id,)
        ).fetchall()
    return {"status": "found", "ticket": dict(ticket), "order": dict(order) if order else None,
            "messages": [dict(r) for r in messages]}
