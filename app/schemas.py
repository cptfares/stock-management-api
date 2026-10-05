from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    unit_price: float = Field(gt=0)
    reorder_threshold: int = Field(default=0, ge=0)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    unit_price: float
    reorder_threshold: int


class ProductReadWithStock(ProductRead):
    total_stock: int
    is_low_stock: bool


class StockAdjustment(BaseModel):
    product_id: int
    warehouse_id: int
    quantity_change: int = Field(description="Positive to add, negative to remove")
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("quantity_change")
    @classmethod
    def _reject_zero(cls, value: int) -> int:
        # A zero change is not a meaningful adjustment; reject it at the edge
        # (422) rather than silently accepting a request that does nothing.
        if value == 0:
            raise ValueError("quantity_change must not be zero")
        return value


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    warehouse_id: int
    quantity_change: int
    reason: str
    created_at: datetime


class StockTransferCreate(BaseModel):
    product_id: int
    source_warehouse_id: int
    destination_warehouse_id: int
    quantity: int = Field(gt=0, description="Number of units to move (positive)")
    reason: str = Field(min_length=1, max_length=200)


class StockTransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    source_warehouse_id: int
    destination_warehouse_id: int
    quantity: int
    reason: str
    created_at: datetime
