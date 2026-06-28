from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.models import Category, Product, User
from app.schemas.schemas import ProductCreate, ProductListOut, ProductOut, ProductStatsOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


def _to_product_out(product: Product) -> ProductOut:
    return ProductOut(
        id=product.id,
        name=product.name,
        category_id=product.category_id,
        category_name=product.category.name,
        reference=product.reference,
        unit_price=product.unit_price,
        quantity=product.quantity,
        unit=product.unit,
        pack_size=product.pack_size,
        created_at=product.created_at,
    )


def _check_owned_category(category_id: int, db: Session, current_user: User) -> None:
    category = db.query(Category).filter(Category.id == category_id, Category.shop_id == current_user.shop_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")


@router.get("", response_model=ProductListOut)
def list_products(
    page: int = 1,
    page_size: int = 10,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    query = (
        db.query(Product)
        .options(joinedload(Product.category))
        .filter(Product.shop_id == current_user.shop_id)
    )
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    total = query.count()
    items = (
        query.order_by(Product.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    total_pages = max((total + page_size - 1) // page_size, 1)

    return ProductListOut(
        items=[_to_product_out(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/stats", response_model=ProductStatsOut)
def product_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    base_query = db.query(Product).filter(Product.shop_id == current_user.shop_id)

    total_products = base_query.count()
    out_of_stock_count = base_query.filter(Product.quantity <= 0).count()

    aggregates = (
        db.query(
            func.coalesce(func.sum(Product.quantity), 0),
            func.coalesce(func.sum(Product.unit_price * Product.quantity), 0),
            func.coalesce(func.avg(Product.unit_price), 0),
        )
        .filter(Product.shop_id == current_user.shop_id)
        .one()
    )
    total_stock_quantity, total_stock_value, average_price = aggregates

    return ProductStatsOut(
        total_products=total_products,
        total_stock_quantity=float(total_stock_quantity or 0),
        total_stock_value=float(total_stock_value or 0),
        out_of_stock_count=out_of_stock_count,
        average_price=float(average_price or 0),
    )


@router.post("", response_model=ProductOut, status_code=201)
def create_product(payload: ProductCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _check_owned_category(payload.category_id, db, current_user)
    product = Product(shop_id=current_user.shop_id, **payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return _to_product_out(product)


def _get_owned_product(product_id: int, db: Session, current_user: User) -> Product:
    product = (
        db.query(Product)
        .options(joinedload(Product.category))
        .filter(Product.id == product_id, Product.shop_id == current_user.shop_id)
        .first()
    )
    if not product:
        raise HTTPException(status_code=404, detail="Article introuvable")
    return product


@router.get("/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _to_product_out(_get_owned_product(product_id, db, current_user))


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    product = _get_owned_product(product_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "category_id" in data:
        _check_owned_category(data["category_id"], db, current_user)
    for field, value in data.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return _to_product_out(product)


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    product = _get_owned_product(product_id, db, current_user)
    db.delete(product)
    db.commit()
