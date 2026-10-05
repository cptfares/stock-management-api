PARIS = 1  # warehouse id seeded by the test fixtures


def _adjust(client, product_id, warehouse_id, quantity_change, reason="test"):
    return client.post(
        "/stocks/adjustments",
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity_change": quantity_change,
            "reason": reason,
        },
    )


def test_removing_all_stock_is_applied_and_recorded(client, make_product):
    # Regression for the no-op bug: emptying a warehouse used to silently do
    # nothing and record nothing (it returned a bare 200).
    pid = make_product()
    assert _adjust(client, pid, PARIS, 10, "received").status_code == 201

    resp = _adjust(client, pid, PARIS, -10, "cleared out")
    assert resp.status_code == 201, resp.text
    assert resp.json()["quantity_change"] == -10

    assert client.get("/products").json()[0]["total_stock"] == 0


def test_cannot_remove_more_than_available(client, make_product):
    pid = make_product()
    _adjust(client, pid, PARIS, 5, "received")
    resp = _adjust(client, pid, PARIS, -10, "oversell")
    assert resp.status_code == 409


def test_zero_change_is_rejected(client, make_product):
    pid = make_product()
    resp = _adjust(client, pid, PARIS, 0, "noop")
    assert resp.status_code == 422


def test_adjust_unknown_product_returns_404(client):
    resp = _adjust(client, 9999, PARIS, 5)
    assert resp.status_code == 404


def test_adjust_unknown_warehouse_returns_404(client, make_product):
    pid = make_product()
    resp = _adjust(client, pid, 9999, 5)
    assert resp.status_code == 404
