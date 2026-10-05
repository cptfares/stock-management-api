PARIS = 1  # warehouse id seeded by the test fixtures


def _adjust(client, product_id, quantity_change):
    return client.post(
        "/stocks/adjustments",
        json={
            "product_id": product_id,
            "warehouse_id": PARIS,
            "quantity_change": quantity_change,
            "reason": "seed",
        },
    )


def test_product_at_threshold_counts_as_low(client, make_product):
    # "<=" means a product sitting exactly on its reorder point is low stock.
    pid = make_product(reorder_threshold=10)
    _adjust(client, pid, 10)
    low = client.get("/products/low-stock").json()
    assert any(p["id"] == pid for p in low)


def test_product_above_threshold_is_not_low(client, make_product):
    pid = make_product(reorder_threshold=10)
    _adjust(client, pid, 11)
    low = client.get("/products/low-stock").json()
    assert all(p["id"] != pid for p in low)


def test_safety_margin_includes_approaching_products(client, make_product):
    pid = make_product(reorder_threshold=10)
    _adjust(client, pid, 13)  # above threshold, but within a margin of 5

    # Not low with the default margin...
    assert all(p["id"] != pid for p in client.get("/products/low-stock").json())

    # ...but surfaced as an early warning within margin 5 (13 <= 10 + 5).
    low = client.get("/products/low-stock", params={"safety_margin": 5}).json()
    match = [p for p in low if p["id"] == pid]
    assert match, "a product within the safety margin should be returned"
    # It is approaching, not yet at the threshold.
    assert match[0]["is_low_stock"] is False


def test_negative_safety_margin_is_rejected(client):
    resp = client.get("/products/low-stock", params={"safety_margin": -1})
    assert resp.status_code == 422
