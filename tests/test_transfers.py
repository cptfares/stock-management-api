import pytest
from sqlalchemy import select

from app import models, services

PARIS = 1  # warehouse ids seeded by the test fixtures
LYON = 2


def _adjust(client, product_id, warehouse_id, quantity_change):
    return client.post(
        "/stocks/adjustments",
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity_change": quantity_change,
            "reason": "seed",
        },
    )


def _transfer(client, product_id, source, destination, quantity, reason="rebalance"):
    return client.post(
        "/stocks/transfers",
        json={
            "product_id": product_id,
            "source_warehouse_id": source,
            "destination_warehouse_id": destination,
            "quantity": quantity,
            "reason": reason,
        },
    )


def test_transfer_moves_stock_and_records_history(client, make_product, db):
    pid = make_product()
    _adjust(client, pid, PARIS, 10)  # Paris = 10

    resp = _transfer(client, pid, PARIS, LYON, 4)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["quantity"] == 4
    assert body["source_warehouse_id"] == PARIS
    assert body["destination_warehouse_id"] == LYON

    # Stock levels updated: Paris 6, Lyon 4.
    paris = db.scalar(
        select(models.StockLevel).where(
            models.StockLevel.product_id == pid,
            models.StockLevel.warehouse_id == PARIS,
        )
    )
    lyon = db.scalar(
        select(models.StockLevel).where(
            models.StockLevel.product_id == pid,
            models.StockLevel.warehouse_id == LYON,
        )
    )
    assert paris.quantity == 6
    assert lyon.quantity == 4

    # Two linked ledger legs (-4 and +4), both carrying the transfer id.
    legs = db.scalars(
        select(models.StockMovement).where(
            models.StockMovement.transfer_id == body["id"]
        )
    ).all()
    assert len(legs) == 2
    assert {leg.quantity_change for leg in legs} == {-4, 4}

    # History endpoint shows it.
    history = client.get("/stocks/transfers").json()
    assert len(history) == 1
    assert history[0]["id"] == body["id"]


def test_insufficient_stock_is_rejected_and_atomic(client, make_product, db):
    pid = make_product()
    _adjust(client, pid, PARIS, 3)

    resp = _transfer(client, pid, PARIS, LYON, 5)  # only 3 available
    assert resp.status_code == 409

    # Nothing moved and nothing was recorded — the whole move rolled back.
    assert client.get("/stocks/transfers").json() == []
    paris = db.scalar(
        select(models.StockLevel).where(
            models.StockLevel.product_id == pid,
            models.StockLevel.warehouse_id == PARIS,
        )
    )
    assert paris.quantity == 3
    lyon = db.scalar(
        select(models.StockLevel).where(
            models.StockLevel.product_id == pid,
            models.StockLevel.warehouse_id == LYON,
        )
    )
    assert lyon is None  # destination level was never created


def test_transfer_to_same_warehouse_is_rejected(client, make_product):
    pid = make_product()
    _adjust(client, pid, PARIS, 10)
    resp = _transfer(client, pid, PARIS, PARIS, 1)
    assert resp.status_code == 400


def test_transfer_unknown_warehouse_returns_404(client, make_product):
    pid = make_product()
    _adjust(client, pid, PARIS, 10)
    resp = _transfer(client, pid, PARIS, 9999, 1)
    assert resp.status_code == 404


def test_transfer_nonpositive_quantity_is_rejected(client, make_product):
    pid = make_product()
    _adjust(client, pid, PARIS, 10)
    resp = _transfer(client, pid, PARIS, LYON, 0)
    assert resp.status_code == 422


def test_history_filters_by_product_and_warehouse(client, make_product):
    p1 = make_product(sku="AAA")
    p2 = make_product(sku="BBB")
    _adjust(client, p1, PARIS, 10)
    _adjust(client, p2, PARIS, 10)
    _transfer(client, p1, PARIS, LYON, 1)
    _transfer(client, p2, PARIS, LYON, 2)

    only_p1 = client.get("/stocks/transfers", params={"product_id": p1}).json()
    assert len(only_p1) == 1
    assert only_p1[0]["product_id"] == p1

    # Warehouse 2 is the destination of both transfers.
    wh2 = client.get("/stocks/transfers", params={"warehouse_id": LYON}).json()
    assert len(wh2) == 2

    # A warehouse involved in no transfer returns an empty history.
    assert client.get("/stocks/transfers", params={"warehouse_id": 999}).json() == []


def test_transfer_rolls_back_when_a_leg_fails(client, make_product, db, monkeypatch):
    # True atomicity: force the SECOND leg to fail *after* the transfer row and the
    # first leg have already been written, and assert the whole move rolls back.
    pid = make_product()
    _adjust(client, pid, PARIS, 10)

    original = services.StockService._apply_transfer_leg
    calls = {"n": 0}

    def flaky_leg(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom on the second leg")
        return original(self, **kwargs)

    monkeypatch.setattr(services.StockService, "_apply_transfer_leg", flaky_leg)

    with pytest.raises(RuntimeError):
        _transfer(client, pid, PARIS, LYON, 4)

    # Nothing persisted: no transfer row, source untouched, destination never created.
    assert db.scalars(select(models.StockTransfer)).all() == []
    paris = db.scalar(
        select(models.StockLevel).where(
            models.StockLevel.product_id == pid,
            models.StockLevel.warehouse_id == PARIS,
        )
    )
    assert paris.quantity == 10  # the first leg's -4 was rolled back
    lyon = db.scalar(
        select(models.StockLevel).where(
            models.StockLevel.product_id == pid,
            models.StockLevel.warehouse_id == LYON,
        )
    )
    assert lyon is None
