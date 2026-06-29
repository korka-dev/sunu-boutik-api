from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.models import Client, User
from app.schemas.schemas import ClientCreate, ClientListOut, ClientOut, ClientUpdate

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=ClientListOut)
def list_clients(
    page: int = 1,
    page_size: int = 10,
    search: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    query = db.query(Client).filter(Client.shop_id == current_user.shop_id)
    if search:
        query = query.filter(
            (Client.name.ilike(f"%{search}%")) | (Client.phone.ilike(f"%{search}%"))
        )
    total = query.count()
    items = (
        query.order_by(Client.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    total_pages = max((total + page_size - 1) // page_size, 1)

    return ClientListOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("", response_model=ClientOut, status_code=201)
def create_client(payload: ClientCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Le nom du client est requis")
    data = payload.model_dump()
    data["name"] = name
    client = Client(shop_id=current_user.shop_id, **data)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def _get_owned_client(client_id: int, db: Session, current_user: User) -> Client:
    client = db.query(Client).filter(Client.id == client_id, Client.shop_id == current_user.shop_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return client


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _get_owned_client(client_id, db, current_user)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(client_id: int, payload: ClientUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = _get_owned_client(client_id, db, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = (data["name"] or "").strip()
        if not data["name"]:
            raise HTTPException(status_code=400, detail="Le nom du client est requis")
    for field, value in data.items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    client = _get_owned_client(client_id, db, current_user)
    db.delete(client)
    db.commit()
