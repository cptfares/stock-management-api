from datetime import datetime, timezone

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    unit_price: Mapped[float]
    reorder_threshold: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
    )


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class StockLevel(Base):
    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[int] = mapped_column(default=0)


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    quantity_change: Mapped[int]
    reason: Mapped[str]
    # Stamp movements in UTC and timezone-aware, matching Product.created_at.
    # Using a column default (rather than setting it by hand at each call site)
    # means every path that records a movement — adjustments and transfers —
    # gets a consistent timestamp and none can forget to set it.
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
    )
    # Links the two legs of a warehouse-to-warehouse transfer back to the
    # StockTransfer that produced them. NULL for ordinary adjustments.
    transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transfers.id"), default=None
    )


class StockTransfer(Base):
    """A warehouse-to-warehouse move, recorded as its own event so the history
    of what moved where is preserved. The two resulting StockMovement rows link
    back here via transfer_id."""

    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    source_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    destination_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[int]
    reason: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
    )
