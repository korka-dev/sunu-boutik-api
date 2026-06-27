from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_admin
from app.core.email import send_shop_approved_email, send_shop_rejected_email
from app.core.security import generate_temp_password, hash_password
from app.db.session import get_db
from app.models.models import Client, Invoice, Product, Shop, ShopStatus, User, UserRole
from app.schemas.schemas import OverviewOut, RejectRequest, ShopAdminOut, ShopListOut, ShopStatsOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview", response_model=OverviewOut)
def overview(db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    status_counts = dict(
        db.query(Shop.status, func.count(Shop.id)).group_by(Shop.status).all()
    )
    invoice_totals = db.query(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0)).one()

    return OverviewOut(
        total_shops=sum(status_counts.values()),
        pending_shops=status_counts.get(ShopStatus.PENDING, 0),
        approved_shops=status_counts.get(ShopStatus.APPROVED, 0),
        rejected_shops=status_counts.get(ShopStatus.REJECTED, 0),
        total_invoices=invoice_totals[0] or 0,
        total_revenue=float(invoice_totals[1] or 0),
    )


def _owner_of(shop: Shop, db: Session) -> User | None:
    return (
        db.query(User)
        .filter(User.shop_id == shop.id, User.role == UserRole.OWNER)
        .order_by(User.id)
        .first()
    )


def _owners_by_shop_id(shop_ids: list[int], db: Session) -> dict[int, User]:
    if not shop_ids:
        return {}
    owners = (
        db.query(User)
        .filter(User.shop_id.in_(shop_ids), User.role == UserRole.OWNER)
        .order_by(User.id)
        .all()
    )
    result: dict[int, User] = {}
    for owner in owners:
        result.setdefault(owner.shop_id, owner)
    return result


def _to_shop_admin_out(shop: Shop, db: Session) -> ShopAdminOut:
    owner = _owner_of(shop, db)
    return _shop_admin_out_with_owner(shop, owner)


def _shop_admin_out_with_owner(shop: Shop, owner: User | None) -> ShopAdminOut:
    return ShopAdminOut(
        id=shop.id,
        name=shop.name,
        address=shop.address,
        phone=shop.phone,
        status=shop.status,
        created_at=shop.created_at,
        reviewed_at=shop.reviewed_at,
        owner_email=owner.email if owner else None,
        owner_name=owner.full_name if owner else None,
    )


@router.get("/shops", response_model=ShopListOut)
def list_shops(
    status_filter: str | None = None,
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    query = db.query(Shop)
    if status_filter:
        query = query.filter(Shop.status == status_filter)

    total = query.count()
    shops = (
        query.order_by(Shop.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    total_pages = max((total + page_size - 1) // page_size, 1)
    owners_by_shop = _owners_by_shop_id([shop.id for shop in shops], db)

    return ShopListOut(
        items=[_shop_admin_out_with_owner(shop, owners_by_shop.get(shop.id)) for shop in shops],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/shops/{shop_id}/stats", response_model=ShopStatsOut)
def shop_stats(shop_id: int, db: Session = Depends(get_db), _admin: User = Depends(get_current_admin)):
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Boutique introuvable")

    products_count = db.query(func.count(Product.id)).filter(Product.shop_id == shop_id).scalar_subquery()
    clients_count = db.query(func.count(Client.id)).filter(Client.shop_id == shop_id).scalar_subquery()
    users_count = db.query(func.count(User.id)).filter(User.shop_id == shop_id).scalar_subquery()
    invoices_count, total_revenue = db.query(
        func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0)
    ).filter(Invoice.shop_id == shop_id).one()

    products_count, clients_count, users_count = db.query(
        products_count, clients_count, users_count
    ).one()

    return ShopStatsOut(
        shop_id=shop.id,
        shop_name=shop.name,
        status=shop.status,
        products_count=products_count,
        clients_count=clients_count,
        invoices_count=invoices_count,
        total_revenue=float(total_revenue),
        users_count=users_count,
    )


@router.post("/shops/{shop_id}/approve", response_model=ShopAdminOut)
def approve_shop(
    shop_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Boutique introuvable")

    shop.status = ShopStatus.APPROVED
    shop.reviewed_at = datetime.utcnow()

    owner = _owner_of(shop, db)
    temp_password = generate_temp_password()
    if owner:
        owner.hashed_password = hash_password(temp_password)
        owner.must_change_password = True
        owner.is_active = True

    db.query(User).filter(User.shop_id == shop_id, User.id != (owner.id if owner else None)).update(
        {User.is_active: True}
    )
    db.commit()

    if owner:
        background_tasks.add_task(
            send_shop_approved_email, owner.full_name, owner.email, shop.name, temp_password
        )

    return _to_shop_admin_out(shop, db)


@router.post("/shops/{shop_id}/reject", response_model=ShopAdminOut)
def reject_shop(
    shop_id: int,
    payload: RejectRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_admin),
):
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Boutique introuvable")

    shop.status = ShopStatus.REJECTED
    shop.reviewed_at = datetime.utcnow()
    db.query(User).filter(User.shop_id == shop_id).update({User.is_active: False})
    db.commit()

    owner = _owner_of(shop, db)
    if owner:
        background_tasks.add_task(send_shop_rejected_email, owner.full_name, owner.email, shop.name, payload.reason)

    return _to_shop_admin_out(shop, db)
