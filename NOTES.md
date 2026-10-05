# Notes — design decisions, assumptions, and changes

## What was delivered
- **Task 1 — transfer stock between warehouses**, with preserved history:
  `POST /stocks/transfers` and `GET /stocks/transfers`.
- **Task 2 — early-warning low-stock**: a `safety_margin` query param on
  `GET /products/low-stock`.
- Fixes to pre-existing issues found along the way (the brief invited this), and
  a `pytest` suite covering the above.

## Task 1 — Transfer between warehouses

**Design.** A transfer is recorded as a first-class `StockTransfer` row (product,
source, destination, quantity, reason, created_at) — that is what answers "see
what moved where later on" via `GET /stocks/transfers`. Each transfer *also*
writes **two linked `StockMovement` rows** (−qty at the source, +qty at the
destination), each carrying a `transfer_id` foreign key back to the transfer.

**Why both a transfer record and movement legs?** The existing `adjust_stock`
already records every quantity change as a `StockMovement`, which establishes the
invariant *a warehouse's current stock = the sum of its movements*. If transfers
changed stock levels without writing movements, that invariant would break and
transfers would be invisible in the per-warehouse ledger. Writing linked legs
keeps the ledger complete, and `transfer_id` rolls the two legs back up into the
business event. (A simpler design — transfer table only, no legs — was
considered and rejected for breaking that invariant.)

**Atomicity.** The transfer row and both legs run inside the single per-request
transaction (`get_db` uses `session.begin()`), so a failure anywhere rolls the
whole move back — no half-applied transfers. A test forces the second leg to fail
mid-transfer and asserts the transfer row and the first leg are both rolled back.

**Validation.** product / source / destination must exist (404); source must
differ from destination (400); `quantity > 0` (422, enforced in the schema);
source must hold enough stock (409).

**Ledger `reason` text.** The user's "why" lives on the `StockTransfer` row; the
two legs get generated, direction-aware descriptions ("Transfer to Lyon
warehouse" / "Transfer from Paris warehouse") so the raw ledger reads on its own,
while `transfer_id` provides the exact machine link.

## Task 2 — Early-warning low-stock
- Added `safety_margin` (query param, default `0`, must be `>= 0`). A product is
  low when `total_stock <= reorder_threshold + safety_margin`.
- **Definition of "low stock": at or below the threshold (`<=`)**, not strictly
  below. The brief says the new version should catch products that haven't
  "already hit" the threshold, which implies that hitting it (`==`) already
  counts as low. This also unified `find_low_stock` with the `is_low_stock` flag,
  which already used `<=` — the two **disagreed before** (a `<` vs `<=` bug).
- With a positive margin, products that are approaching but not yet at the
  threshold come back with `is_low_stock: false`, so a single call distinguishes
  "reorder now" (`true`) from "watch" (`false`).

## Fixes to pre-existing code (the brief invited this)
- **`adjust_stock` no-op bug.** The zero-check compared the *resulting total* to
  zero instead of the *requested change*, so removing all of a warehouse's stock
  (e.g. 42, then −42) silently did nothing and logged nothing. A zero change is
  now rejected at the schema with `422` — a zero adjustment isn't meaningful, and
  rejecting at the edge also removed an awkward empty-`200` response that
  contradicted the endpoint's declared `201` + response model.
- **Negative stock.** Adjustments and transfers can no longer drive a stock level
  below zero (409).
- **Missing validation / foreign keys.** Adjusting or transferring for a
  non-existent product/warehouse used to create orphan rows. Now returns `404`,
  and foreign keys are enforced at the DB level via `PRAGMA foreign_keys=ON`
  (SQLite ignores FK constraints otherwise; a production Postgres enforces them
  natively).
- **Timestamps.** `StockMovement.created_at` had no default and was set with
  naive local time, while `Product.created_at` used UTC-aware time. Unified on a
  UTC-aware column default so every write path is consistent.
- **`reorder_threshold` validation** moved into the schema (`ge=0`) for
  consistency with the other field constraints (`unit_price > 0`, etc.).
- **Dead code removed:** `SERVICE_STARTUP_TIME` (unused; used the deprecated
  `datetime.utcnow()`), `_describe_movement` and `_normalize_sku` (never called),
  and two unreachable branches in `create_product`.

## Tests
`tests/` (run with `python -m pytest`) covers:
- **Transfers:** happy path (levels move; two linked movements with `transfer_id`);
  true atomicity (a forced mid-transfer failure rolls back the transfer row and
  the first leg); insufficient stock → 409 (rejected before any write);
  same-warehouse (400); unknown warehouse (404); non-positive quantity (422);
  history filters.
- **Adjustments:** empty-a-warehouse works and is recorded (the no-op fix);
  insufficient stock (409); unknown product/warehouse (404); zero rejected (422).
- **Low-stock:** `<=` boundary (at threshold counts); above threshold excluded;
  safety margin surfaces approaching products with `is_low_stock: false`;
  negative margin rejected (422).

## Known limitations / what I'd do at scale
- **N+1 queries** in `list_products_with_stock` (one SUM per product). Fine at
  this scale; at scale, collapse into a single `GROUP BY` / `HAVING` query.
- **Money as float** (`unit_price`): acceptable here, but real money should be
  integer cents or `Decimal` to avoid floating-point rounding.
- **No `GET /warehouses` / per-warehouse stock view.** Warehouses are only seeded
  and referenced by id — you can transfer between warehouses you can't enumerate
  through the API. A natural next addition.
- **SKU matching is case-sensitive** (the intended normalization helper was dead
  code and was removed rather than wired in).
- **Concurrency (TOCTOU).** Stock is checked then written without a row lock.
  SQLite serializes writes so it is safe here; on Postgres I'd use
  `SELECT … FOR UPDATE` or a DB check constraint to prevent overselling under
  concurrent requests.
- **No migrations.** Schema is created with `create_all`; a real deployment would
  use Alembic (and `create_all` would not add new columns to an existing DB).
