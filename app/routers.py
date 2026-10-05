from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models, schemas, services
from .database import get_db

router = APIRouter()


@router.post("/products", response_model=schemas.ProductRead, status_code=201)
def create_product(data: schemas.ProductCreate, db: Session = Depends(get_db)):
    # Pre-check SKU uniqueness so we return a friendly 409 instead of a 500
    # surfaced from the database unique constraint.
    existing = db.scalar(select(models.Product).where(models.Product.sku == data.sku))
    if existing is not None:
        raise HTTPException(409, f"Product with SKU '{data.sku}' already exists")

    service = services.ProductService(db)
    product = service.create_product(data)
    return product


@router.get("/products", response_model=list[schemas.ProductReadWithStock])
def list_products(db: Session = Depends(get_db)):
    service = services.ProductService(db)
    items = service.list_products_with_stock()
    return [
        schemas.ProductReadWithStock.model_validate(
            {
                **item["product"].__dict__,
                "total_stock": item["total_stock"],
                "is_low_stock": item["is_low_stock"],
            }
        )
        for item in items
    ]


@router.get(
    "/products/low-stock",
    response_model=list[schemas.ProductReadWithStock],
)
def list_low_stock(
    safety_margin: int = Query(0, ge=0, description="Early-warning buffer, in units."),
    db: Session = Depends(get_db),
):
    service = services.ProductService(db)
    items = service.find_low_stock(safety_margin=safety_margin)
    return [
        schemas.ProductReadWithStock.model_validate(
            {
                **item["product"].__dict__,
                "total_stock": item["total_stock"],
                "is_low_stock": item["is_low_stock"],
            }
        )
        for item in items
    ]


@router.post(
    "/stocks/adjustments",
    response_model=schemas.StockMovementRead,
    status_code=201,
)
def adjust_stock(data: schemas.StockAdjustment, db: Session = Depends(get_db)):
    service = services.StockService(db)
    return service.adjust_stock(data)


@router.post(
    "/stocks/transfers",
    response_model=schemas.StockTransferRead,
    status_code=201,
)
def create_transfer(data: schemas.StockTransferCreate, db: Session = Depends(get_db)):
    service = services.StockService(db)
    return service.transfer_stock(data)


@router.get("/stocks/transfers", response_model=list[schemas.StockTransferRead])
def list_transfers(
    product_id: int | None = Query(None, description="Filter by product"),
    warehouse_id: int | None = Query(
        None, description="Filter by warehouse (matches source or destination)"
    ),
    db: Session = Depends(get_db),
):
    service = services.StockService(db)
    return service.list_transfers(product_id=product_id, warehouse_id=warehouse_id)
