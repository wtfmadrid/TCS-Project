"""Generate reproducible SYNTHETIC retail support data; no LLM/API needed."""

import argparse
import random
import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from contextlib import closing

from database import DB_PATH, initialize_database

SEED = 42
AS_OF = date(2026, 10, 1)
TABLES = ("customers", "orders", "support_tickets", "ticket_messages")


def generate_data():
    rng = random.Random(SEED)
    named = [
        ("Ema Wilson", "ema.wilson"), ("Liam Patel", "liam.patel"),
        ("Sophia Chen", "sophia.chen"), ("Ema Brown", "ema.brown"),
        ("Noah Singh", "noah.singh"), ("Liam Chen", "liam.chen"),
        ("Sophia Patel", "sophia.patel"), ("Noah Wilson", "noah.wilson"),
        ("Alex Morgan", "alex.morgan.9"), ("Alex Morgan", "alex.morgan.10"),
        ("Priya Shah", "priya.shah"), ("Priya Mehta", "priya.mehta"),
    ]
    first = ["Aarav", "Maya", "Daniel", "Olivia", "Sam", "Jordan", "Aisha", "Lucas", "Meera", "Ethan", "Sara", "James"]
    last = ["Shah", "Chen", "Wilson", "Patel", "Brown", "Singh", "Martin", "Wong", "Ahmed", "Lee", "Roy", "Taylor"]
    customers = []
    for cid in range(1, 76):
        if cid <= len(named):
            name, email = named[cid - 1]
        else:
            name = f"{rng.choice(first)} {rng.choice(last)}"
            email = name.lower().replace(" ", ".") + f".{cid}"
        joined = date(2024, 1, 1) + timedelta(days=rng.randrange(600))
        customers.append((cid, name, email + "@example.com",
                          "inactive" if cid == 3 or cid % 17 == 0 else "active",
                          "premium" if cid % 4 == 0 else "standard", joined.isoformat()))

    # Curated cases have stable IDs for evaluation. Dates refer to a fixed snapshot.
    orders = [
        (1001, 1, "Wireless headphones", "electronics", "2026-09-15", "2026-09-18", 12999, "CAD", "delivered"),
        (1002, 1, "Desk lamp", "home", "2026-08-01", "2026-08-07", 4599, "CAD", "delivered"),
        (1003, 1, "Travel backpack", "accessories", "2026-09-24", "2026-09-27", 7999, "CAD", "delivered"),
        (1004, 4, "Running shoes", "footwear", "2026-09-10", None, 8999, "CAD", "delivered"),
        (1005, 2, "Coffee maker", "home", "2026-09-02", "2026-09-06", 9999, "CAD", "delivered"),
    ]
    catalog = [("Wireless mouse", "electronics", 2999), ("Desk lamp", "home", 4599),
               ("Travel backpack", "accessories", 7999), ("Running shoes", "footwear", 8999),
               ("Cotton jacket", "clothing", 6999), ("Coffee maker", "home", 9999),
               ("USB-C charger", "electronics", 3499), ("Water bottle", "accessories", 2499)]
    # Customers 5 and 75 have no orders; 71-75 have no tickets.
    pool = [cid for cid in range(6, 75)]
    for oid in range(1006, 1201):
        cid = pool[(oid - 1006) % len(pool)] if oid < 1075 else rng.choice(pool)
        product, category, amount = rng.choice(catalog)
        purchased = date(2026, 1, 1) + timedelta(days=rng.randrange(235))
        status = rng.choices(["delivered", "returned", "cancelled", "shipped", "processing"], [70, 10, 8, 8, 4])[0]
        if status in {"shipped", "processing"}:
            purchased = AS_OF - timedelta(days=rng.randint(1, 4))
        delivered = purchased + timedelta(days=rng.randint(2, 7)) if status in {"delivered", "returned"} else None
        orders.append((oid, cid, product, category, purchased.isoformat(),
                       delivered.isoformat() if delivered else None, amount, "CAD", status))

    tickets, messages = [], []

    def add_ticket(tid, cid, oid, subject, category, priority, status, created, description, reply, resolution=None, followup=None):
        start = datetime.fromisoformat(created)
        if status == "resolved" and not resolution:
            raise ValueError("Resolved tickets require a resolution")
        entries = [("customer", description), ("support", reply)]
        if followup:
            entries.append(("customer", followup))
        if resolution:
            entries.append(("support", resolution))
        closed = (start + timedelta(hours=2 * (len(entries) - 1))).isoformat() if resolution else None
        tickets.append((tid, cid, oid, subject, category, priority, status, created, description, resolution, closed))
        for index, (role, text) in enumerate(entries):
            messages.append((len(messages) + 1, tid, role,
                             (start + timedelta(hours=2 * index)).isoformat(), text))

    add_ticket(101, 1, 1001, "Refund requested for damaged item", "refund", "high", "open",
               "2026-09-28T09:00:00", "My headphones arrived damaged. I would like a refund.",
               "We received your message and a reference to submitted photos. The photos and refund eligibility have not been reviewed.",
               followup="I submitted two photos. Please let me know what else you need.")
    add_ticket(102, 1, 1002, "Delivery tracking unavailable", "shipping", "normal", "resolved",
               "2026-08-05T09:00:00", "The tracking link for my desk lamp does not work.",
               "We are checking the tracking link.", "A working tracking link was supplied; the tracking-access issue is resolved.")
    add_ticket(103, 1, 1003, "Duplicate charge reported", "billing", "high", "pending",
               "2026-09-30T09:00:00", "I see two charges for my backpack purchase.",
               "Billing is investigating. We have not confirmed whether either charge is a temporary authorization.")
    add_ticket(104, 2, None, "Change account email", "account", "low", "resolved",
               "2026-09-10T09:00:00", "Please change my account email to liam.patel@example.com.",
               "We will verify your identity before making this change.", "Identity verified and email updated to liam.patel@example.com.")
    add_ticket(105, 3, None, "Unable to sign in", "account", "normal", "open",
               "2026-09-29T09:00:00", "I cannot sign in to my account.",
               "Your account is inactive. We are reviewing the account status.")
    add_ticket(106, 4, 1004, "Return instructions requested", "returns", "normal", "pending",
               "2026-09-27T09:00:00", "I want to return my running shoes. What do I need to provide?",
               "The order is marked delivered, but the delivery date is missing. Please confirm the delivery date and item condition.")
    add_ticket(107, 1, 1001, "Follow-up on damaged headphones", "refund", "high", "pending",
               "2026-09-30T10:00:00", "I am following up on my damaged-headphones complaint in ticket 101.",
               "This follow-up concerns the same order as ticket 101. Review is still pending; no refund has been approved.")

    templates = {
        "refund": [
            ("Refund status inquiry", "Could you check the refund status for order {oid}?", "We are checking the payment records; this message does not confirm refund approval."),
            ("Damaged item reported", "My {product} from order {oid} arrived damaged. Can you review it?", "Please provide photos and describe the damage. Eligibility has not yet been determined."),
        ],
        "returns": [
            ("Return instructions", "How do I return the {product} from order {oid}?", "Please confirm the item condition. We will check the applicable policy."),
            ("Return package tracking", "Can you check my return for order {oid}?", "Please provide the return tracking number so we can investigate."),
        ],
        "shipping": [
            ("Tracking link unavailable", "The tracking link for order {oid} is not working.", "We are checking the carrier tracking link."),
            ("Delivery update requested", "Please provide a delivery update for order {oid}.", "We are checking the carrier's latest update."),
        ],
        "billing": [
            ("Receipt requested", "Please send a receipt for order {oid}.", "We are retrieving the receipt for this order."),
            ("Charge clarification", "Please explain the charge for order {oid}.", "We are checking the payment record for this order."),
        ],
        "account": [
            ("Password reset requested", "I need help resetting my password.", "We are starting the password-reset process."),
            ("Notification preferences", "How can I change my notification preferences?", "We are reviewing the available account preference settings."),
        ],
    }
    eligible_orders = [o for o in orders if 6 <= o[1] <= 70]
    for tid in range(108, 401):
        order = rng.choice(eligible_orders)
        oid, cid, product, _, ordered, delivered, _, _, order_status = order
        categories = ["billing", "shipping", "account"]
        if order_status in {"delivered", "returned"}:
            categories += ["refund", "returns"]
        category = rng.choice(categories)
        # Completed returns are always tied to a resolved return case.
        if order_status == "returned":
            category = "returns"
        status = "resolved" if order_status == "returned" else rng.choices(["open", "pending", "resolved"], [25, 35, 40])[0]
        subject, description, reply = rng.choice(templates[category])
        if order_status == "returned":
            subject, description, reply = ("Return receipt confirmation", "Please confirm receipt of the return for order {oid}.", "We are checking the warehouse receipt.")
        if order_status == "cancelled" and category == "shipping":
            subject, description, reply = ("Shipment clarification", "Was cancelled order {oid} shipped?", "We are checking whether a parcel was dispatched before cancellation.")
        base = date.fromisoformat(delivered or ordered)
        latest = AS_OF - timedelta(days=1)
        opened = base + timedelta(days=rng.randint(0, min(12, (latest - base).days)))
        resolution = None
        if status == "resolved":
            resolution = {
                "refund": "The customer withdrew the refund inquiry and requested no further action. No refund was issued for this ticket.",
                "returns": "Warehouse receipt of the return was confirmed." if order_status == "returned" else "The customer decided to keep the item. The return inquiry was closed.",
                "shipping": "The order status was explained to the customer and the delivery inquiry was closed.",
                "billing": "The billing information was supplied to the customer and the inquiry was closed.",
                "account": "Account assistance was provided and the customer confirmed the issue was resolved.",
            }[category]
        add_ticket(tid, cid, None if category == "account" else oid, subject, category,
                   rng.choices(["low", "normal", "high"], [20, 60, 20])[0], status,
                   opened.isoformat() + "T09:00:00", description.format(oid=oid, product=product), reply,
                   resolution, "Please keep me updated." if status == "pending" and rng.random() < 0.5 else None)
    return customers, orders, tickets, messages


def seed_database(reset=False, path=None):
    target = Path(path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not reset:
        initialize_database(target)  # Clear instruction if it is the old schema.
        with closing(sqlite3.connect(target)) as conn, conn:
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
        if counts["customers"]:
            print("Existing database kept unchanged. Use --reset to rebuild with a backup.")
            return counts
        if any(counts.values()):
            raise RuntimeError("Database contains partial data. Use --reset to rebuild with a backup.")

    with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".db", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        initialize_database(temporary)
        data = generate_data()
        with closing(sqlite3.connect(temporary)) as conn, conn:
            conn.execute("PRAGMA foreign_keys = ON")
            for table, rows in zip(TABLES, data):
                placeholders = ",".join("?" for _ in rows[0])
                conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign-key validation failed")
        if target.exists():
            backup = target.with_name(f"customers.backup-{datetime.now():%Y%m%d-%H%M%S-%f}.db")
            # SQLite's backup API also preserves committed data in a WAL file.
            with closing(sqlite3.connect(target)) as source, closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
            print(f"Backup saved: {backup}")
        temporary.replace(target)
        return {table: len(rows) for table, rows in zip(TABLES, data)}
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Back up any existing database, then rebuild synthetic data.")
    args = parser.parse_args()
    try:
        result = seed_database(reset=args.reset)
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Database: {DB_PATH}")
    print(f"Synthetic snapshot: {AS_OF}; random seed: {SEED}")
    for table, count in result.items():
        print(f"{table}: {count}")
