from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.email import send_signup_pending_emails
from app.core.limiter import limiter
from app.core.security import create_access_token, hash_password, verify_password
from app.core.uploads import save_shop_logo
from app.db.session import get_db
from app.models.models import Shop, ShopStatus, User
from app.schemas.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeOut,
    RegisterResponse,
    ShopOut,
    Token,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    background_tasks: BackgroundTasks,
    shop_name: str = Form(...),
    shop_address: str | None = Form(None),
    shop_phone: str | None = Form(None),
    full_name: str = Form(...),
    email: str = Form(...),
    logo: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    shop = Shop(
        name=shop_name,
        address=shop_address,
        phone=shop_phone,
        status=ShopStatus.PENDING,
    )
    db.add(shop)
    db.flush()

    if logo and logo.filename:
        shop.logo_path = await save_shop_logo(shop.id, logo)

    user = User(
        shop_id=shop.id,
        full_name=full_name,
        email=email,
        hashed_password=None,
        is_active=False,
    )
    db.add(user)
    db.commit()

    background_tasks.add_task(send_signup_pending_emails, shop.name, user.full_name, user.email)

    return RegisterResponse(
        message="Votre demande a été enregistrée. Elle est en cours de traitement par notre équipe."
    )


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    if user.role != "admin":
        shop = db.query(Shop).filter(Shop.id == user.shop_id).first()
        if not shop or shop.status == ShopStatus.PENDING:
            raise HTTPException(
                status_code=403,
                detail="Votre demande est en cours de traitement. Vous ne pouvez pas encore vous connecter.",
            )
        if shop.status == ShopStatus.REJECTED:
            raise HTTPException(status_code=403, detail="Votre demande a été rejetée.")

    if not user.is_active or not user.hashed_password:
        raise HTTPException(status_code=403, detail="Compte désactivé")

    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token)


@router.get("/me", response_model=MeOut)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    shop = db.query(Shop).filter(Shop.id == current_user.shop_id).first() if current_user.shop_id else None
    return MeOut(
        user=UserOut.model_validate(current_user),
        shop=ShopOut.model_validate(shop) if shop else None,
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.hashed_password or not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Mot de passe actuel incorrect")

    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Le nouveau mot de passe doit contenir au moins 6 caractères")

    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_change_password = False
    db.commit()
