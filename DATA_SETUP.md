# Expanded customer-support data layer

This step replaces the earlier two-table prototype with four tables in one SQLite
database. All records are synthetic and use a fixed snapshot of 2026-10-01.
Generated conversations use templates; they are not real customer conversations.
No company policy is invented by this dataset. Policy rules will come from PDFs.

## Install in the existing VS Code project

1. Copy `database.py`, `seed_db.py`, and `check_database.py` into the project root,
   replacing the earlier two Python files. Keep `.venv`, `.gitignore`, and your
   requirements files. No new packages are needed.
2. Close any application or database viewer using `customers.db`.
3. In PowerShell, from the project root:

```powershell
.\.venv\Scripts\python.exe seed_db.py --reset
.\.venv\Scripts\python.exe check_database.py
```

`--reset` creates and validates a new database first, saves a timestamped backup
of the existing database in `data/`, then replaces `data/customers.db`. It is a
deliberate rebuild, not a migration preserving custom records in the active DB.
Backups retain old records. Do not run it while another process uses the database.
Running without `--reset` keeps an existing populated version-2 database unchanged.

The data directory remains excluded by the existing `.gitignore`. Commit the
generator so another developer can reproduce the data.

## Model

- `customers`: 75 identities, including shared first names and identical full names.
- `orders`: 200 orders; amounts are integer cents in CAD.
- `support_tickets`: 300 tickets, linked to a customer and optionally an order.
- `ticket_messages`: chronological customer/support conversations per ticket.

A composite foreign key ensures a ticket's order belongs to that same customer.
Retrieval connections are read-only, SQL values are parameterized, and an exact
email or customer ID resolves ambiguous names. Agents must ask for clarification
before selecting one of multiple matches.

The seed is deterministic (`random.Random(42)`), independent of the actual current
date. A single-product order model keeps the assessment scope small; there are no
line-item or partial-refund calculations. Data validation checks temporal and
relational consistency. It does not establish that a customer's claim is true.

## Retrieval functions for the next MCP step

| Function | Purpose |
|---|---|
| `find_customer(name_or_email)` | Return found, ambiguous, or not_found |
| `get_customer_overview(customer_id)` | Profile, ticket counts, order count |
| `get_customer_orders(customer_id)` | Order history |
| `get_customer_tickets(customer_id, status=None)` | All or filtered tickets |
| `get_ticket_details(ticket_id)` | Ticket, associated order, and messages |

These are support-agent lookup tools, not a user-authentication boundary.
Names use basic case-insensitive matching; fuzzy/semantic customer matching is
outside this version. Small per-customer result sets are returned without truncation.

## Stable evaluation cases

| Input | Expected evidence |
|---|---|
| Ema / Liam / Sophia / Noah / Priya | Multiple candidates; ask for clarification |
| Alex Morgan | Two identical full names, distinct IDs and emails |
| ema.wilson@example.com | Customer 1; three orders and four tickets |
| Ema Wilson open tickets | Ticket 101 |
| Ticket 101 and ticket 107 | Both concern order 1001; do not count as two damaged orders |
| Ticket 101 | Damage is a customer claim; photos referenced, not inspected |
| Ticket 106 | Delivery date is missing; item condition is not established |
| Ticket 104 | Account issue without an order link |
| Noah Singh (customer 5) | Existing customer with no orders or tickets |
| Customer 999 | Missing customer, distinct from an empty history |

Ema's earlier three-ticket demo now has four tickets because ticket 107 is an
intentional follow-up. Historical resolution text is evidence of a past action,
not a general rule or permission to approve a new refund.
