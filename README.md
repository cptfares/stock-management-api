# Stock Management API

A small FastAPI service for managing products, warehouses, and stock levels.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Note: on macOS with Homebrew's Python 3.14, `python3 -m venv` can currently
> fail inside `ensurepip`. If that happens, create the venv with an earlier
> interpreter, e.g. `python3.13 -m venv .venv`.

## Run

```bash
python -m uvicorn app.main:app --reload
```

The API is then available at http://localhost:8000, with interactive docs at
http://localhost:8000/docs.

Two warehouses (`Paris warehouse`, `Lyon warehouse`) are seeded automatically
on first run.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Endpoints

### Products
- `POST /products` — create a product
- `GET /products` — list products with total stock across all warehouses
- `GET /products/low-stock` — list products **at or below** their reorder
  threshold. Optional `safety_margin` query param (default `0`, must be `>= 0`)
  turns it into an early-warning view: a product is returned when
  `total_stock <= reorder_threshold + safety_margin`. Products that are merely
  *approaching* the threshold come back with `is_low_stock: false`, so one call
  distinguishes "reorder now" from "watch".

### Stock
- `POST /stocks/adjustments` — record a stock movement in one warehouse
  (`quantity_change` positive to add, negative to remove; must be non-zero)
- `POST /stocks/transfers` — move stock from one warehouse to another. Validates
  that the product and both warehouses exist, that source and destination
  differ, and that the source holds enough stock; both sides are applied
  atomically and recorded as history.
- `GET /stocks/transfers` — transfer history ("what moved where"), optionally
  filtered by `product_id` and/or `warehouse_id` (matches either side).

## Project layout

```
app/
├── main.py        # FastAPI app, table creation, warehouse seeding
├── database.py    # SQLAlchemy engine, session, get_db dependency, FK pragma
├── models.py      # SQLAlchemy ORM models
├── schemas.py     # Pydantic request/response schemas
├── services.py    # Business logic (ProductService, StockService)
└── routers.py     # HTTP endpoints
tests/             # pytest suite (adjustments, low-stock, transfers)
NOTES.md           # design decisions, assumptions, and known limitations
```

See [`NOTES.md`](NOTES.md) for design decisions and known limitations.
