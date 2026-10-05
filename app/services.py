from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import models, schemas


class ProductService:
    def __init__(self, db: Session):
        self.db = db

    def create_product(self, data: schemas.ProductCreate) -> models.Product:
        product = models.Product(
            sku=data.sku,
            name=data.name,
            unit_price=data.unit_price,
            reorder_threshold=data.reorder_threshold,
        )
        self.db.add(product)
        self.db.flush()
        return product

    # Results are ordered by name so callers see a stable ordering across calls.
    def list_products(self) -> list[models.Product]:
        stmt = select(models.Product).order_by(models.Product.name)
        return list(self.db.scalars(stmt))

    def list_products_with_stock(self) -> list[dict]:
        products = self.list_products()
        result = []
        for product in products:
            total = self.db.scalar(
                select(func.coalesce(func.sum(models.StockLevel.quantity), 0)).where(
                    models.StockLevel.product_id == product.id
                )
            )
            total = total or 0
            result.append({
                "product": product,
                "total_stock": total,
                "is_low_stock": total <= product.reorder_threshold,
            })
        return result

    def find_low_stock(self, safety_margin: int = 0) -> list[dict]:
        # "Low stock" means at or below the reorder threshold (<=), so a product
        # sitting exactly on its reorder point counts; this also keeps the result
        # consistent with the is_low_stock flag above. safety_margin widens the
        # net for an early warning: products within `safety_margin` units of the
        # threshold (or below) are returned. Defaults to 0 = original behaviour.
        #
        # N+1 caveat: list_products_with_stock() runs one SUM query per product.
        # Fine at this scale; at scale, fold this into one GROUP BY/HAVING query.
        items = self.list_products_with_stock()
        return [
            item
            for item in items
            if item["total_stock"]
            <= item["product"].reorder_threshold + safety_margin
        ]


class StockService:
    def __init__(self, db: Session):
        self.db = db

    def adjust_stock(self, data: schemas.StockAdjustment) -> models.StockMovement:
        # Validate the referenced entities up front so the caller gets a clear
        # 404 instead of a foreign-key IntegrityError (500) at commit — and so
        # we never create a stock level pointing at a product/warehouse that
        # does not exist.
        if self.db.get(models.Product, data.product_id) is None:
            raise HTTPException(404, f"Product {data.product_id} not found")
        if self.db.get(models.Warehouse, data.warehouse_id) is None:
            raise HTTPException(404, f"Warehouse {data.warehouse_id} not found")

        stock_level = self.db.scalar(
            select(models.StockLevel).where(
                models.StockLevel.product_id == data.product_id,
                models.StockLevel.warehouse_id == data.warehouse_id,
            )
        )
        if stock_level is None:
            stock_level = models.StockLevel(
                product_id=data.product_id, warehouse_id=data.warehouse_id, quantity=0
            )
            self.db.add(stock_level)

        # Reject adjustments that would drive stock below zero — a warehouse
        # cannot physically hold a negative quantity. Landing exactly on 0 is
        # allowed (that is simply emptying the stock level).
        if stock_level.quantity + data.quantity_change < 0:
            raise HTTPException(
                409,
                f"Insufficient stock: cannot change by {data.quantity_change}, "
                f"only {stock_level.quantity} on hand",
            )

        stock_level.quantity += data.quantity_change

        # Record the movement for audit purposes. created_at is stamped
        # automatically by the model's UTC-aware column default.
        movement = models.StockMovement(
            product_id=data.product_id,
            warehouse_id=data.warehouse_id,
            quantity_change=data.quantity_change,
            reason=data.reason,
        )
        self.db.add(movement)
        self.db.flush()
        return movement

    def transfer_stock(self, data: schemas.StockTransferCreate) -> models.StockTransfer:
        # Validate the referenced entities up front (clear 404 instead of a DB
        # IntegrityError), and keep the warehouse objects so we can name them in
        # the ledger legs.
        if self.db.get(models.Product, data.product_id) is None:
            raise HTTPException(404, f"Product {data.product_id} not found")
        source = self.db.get(models.Warehouse, data.source_warehouse_id)
        if source is None:
            raise HTTPException(404, f"Warehouse {data.source_warehouse_id} not found")
        destination = self.db.get(models.Warehouse, data.destination_warehouse_id)
        if destination is None:
            raise HTTPException(
                404, f"Warehouse {data.destination_warehouse_id} not found"
            )

        if data.source_warehouse_id == data.destination_warehouse_id:
            raise HTTPException(
                400, "Source and destination warehouses must be different"
            )

        # The source must actually hold enough to move (same rule as the
        # negative-stock guard in adjust_stock, applied to the outgoing leg).
        source_level = self.db.scalar(
            select(models.StockLevel).where(
                models.StockLevel.product_id == data.product_id,
                models.StockLevel.warehouse_id == data.source_warehouse_id,
            )
        )
        available = source_level.quantity if source_level is not None else 0
        if available < data.quantity:
            raise HTTPException(
                409,
                f"Insufficient stock: tried to move {data.quantity}, only "
                f"{available} available in warehouse {data.source_warehouse_id}",
            )

        # Record the transfer event first so we have its id to link the two
        # ledger legs. Everything runs in the request's single transaction
        # (get_db), so if any step fails the whole move rolls back — the legs
        # can never be half-applied.
        transfer = models.StockTransfer(
            product_id=data.product_id,
            source_warehouse_id=data.source_warehouse_id,
            destination_warehouse_id=data.destination_warehouse_id,
            quantity=data.quantity,
            reason=data.reason,
        )
        self.db.add(transfer)
        self.db.flush()  # assigns transfer.id

        self._apply_transfer_leg(
            product_id=data.product_id,
            warehouse_id=data.source_warehouse_id,
            quantity_change=-data.quantity,
            reason=f"Transfer to {destination.name}",
            transfer_id=transfer.id,
        )
        self._apply_transfer_leg(
            product_id=data.product_id,
            warehouse_id=data.destination_warehouse_id,
            quantity_change=data.quantity,
            reason=f"Transfer from {source.name}",
            transfer_id=transfer.id,
        )
        self.db.flush()
        return transfer

    def _apply_transfer_leg(
        self,
        *,
        product_id: int,
        warehouse_id: int,
        quantity_change: int,
        reason: str,
        transfer_id: int,
    ) -> None:
        # Update one warehouse's stock level and record a linked ledger entry.
        # (Source sufficiency is checked in transfer_stock, so no leg goes
        # negative here.)
        stock_level = self.db.scalar(
            select(models.StockLevel).where(
                models.StockLevel.product_id == product_id,
                models.StockLevel.warehouse_id == warehouse_id,
            )
        )
        if stock_level is None:
            stock_level = models.StockLevel(
                product_id=product_id, warehouse_id=warehouse_id, quantity=0
            )
            self.db.add(stock_level)
        stock_level.quantity += quantity_change

        self.db.add(
            models.StockMovement(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity_change=quantity_change,
                reason=reason,
                transfer_id=transfer_id,
            )
        )

    def list_transfers(
        self, *, product_id: int | None = None, warehouse_id: int | None = None
    ) -> list[models.StockTransfer]:
        # Most recent first, so the history reads naturally.
        stmt = select(models.StockTransfer).order_by(
            models.StockTransfer.created_at.desc()
        )
        if product_id is not None:
            stmt = stmt.where(models.StockTransfer.product_id == product_id)
        if warehouse_id is not None:
            # A warehouse can be on either side of a transfer.
            stmt = stmt.where(
                or_(
                    models.StockTransfer.source_warehouse_id == warehouse_id,
                    models.StockTransfer.destination_warehouse_id == warehouse_id,
                )
            )
        return list(self.db.scalars(stmt))
