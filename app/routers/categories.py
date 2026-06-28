from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.models import Category, Product, User
from app.schemas.schemas import CategoryCreate, CategoryListOut, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=CategoryListOut)
def list_categories(
    page: int = 1,
    page_size: int = 10,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    query = db.query(Category).filter(Category.shop_id == current_user.shop_id)
    if search:
        query = query.filter(Category.name.ilike(f"%{search}%"))
    total = query.count()
    items = (
        query.order_by(Category.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    total_pages = max((total + page_size - 1) // page_size, 1)

    return CategoryListOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


def _check_name_available(name: str, db: Session, current_user: User, exclude_id: int | None = None) -> None:
    query = db.query(Category).filter(
        Category.shop_id == current_user.shop_id,
        func.lower(Category.name) == name.strip().lower(),
    )
    if exclude_id is not None:
        query = query.filter(Category.id != exclude_id)
    if query.first():
        raise HTTPException(status_code=400, detail="Une catégorie avec ce nom existe déjà")


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom de la catégorie est requis")
    _check_name_available(name, db, current_user)
    category = Category(shop_id=current_user.shop_id, name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def _get_owned_category(category_id: int, db: Session, current_user: User) -> Category:
    category = db.query(Category).filter(Category.id == category_id, Category.shop_id == current_user.shop_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Catégorie introuvable")
    return category


@router.get("/{category_id}", response_model=CategoryOut)
def get_category(category_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_owned_category(category_id, db, current_user)


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, payload: CategoryUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    category = _get_owned_category(category_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Le nom de la catégorie est requis")
        _check_name_available(name, db, current_user, exclude_id=category_id)
        data["name"] = name
    for field, value in data.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    category = _get_owned_category(category_id, db, current_user)
    has_products = db.query(Product).filter(Product.category_id == category_id).first()
    if has_products:
        raise HTTPException(status_code=400, detail="Impossible de supprimer : des articles sont rattachés à cette catégorie")
    db.delete(category)
    db.commit()
