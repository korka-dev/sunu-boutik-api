from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator


# ---------- Auth ----------

class RegisterRequest(BaseModel):
    shop_name: str
    shop_address: Optional[str] = None
    shop_phone: Optional[str] = None
    full_name: str
    email: EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    message: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    role: str
    shop_id: Optional[int] = None
    must_change_password: bool


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    status: str


class MeOut(BaseModel):
    user: UserOut
    shop: Optional[ShopOut] = None


# ---------- Admin ----------

class ShopAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None
    status: str
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    owner_email: Optional[str] = None
    owner_name: Optional[str] = None


class ShopStatsOut(BaseModel):
    shop_id: int
    shop_name: str
    status: str
    products_count: int
    clients_count: int
    invoices_count: int
    total_revenue: float
    users_count: int


class RejectRequest(BaseModel):
    reason: Optional[str] = None


class OverviewOut(BaseModel):
    total_shops: int
    pending_shops: int
    approved_shops: int
    rejected_shops: int
    total_invoices: int
    total_revenue: float


class ShopListOut(BaseModel):
    items: list[ShopAdminOut]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------- Categories ----------

class CategoryCreate(BaseModel):
    name: str


class CategoryUpdate(BaseModel):
    name: Optional[str] = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class CategoryListOut(BaseModel):
    items: list[CategoryOut]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------- Products ----------

class ProductCreate(BaseModel):
    name: str
    category_id: int
    reference: Optional[str] = None
    unit_price: float = Field(ge=0)
    quantity: float = Field(default=0, ge=0)
    unit: str = "unite"
    pack_size: float = Field(default=1, ge=1)


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[int] = None
    reference: Optional[str] = None
    unit_price: Optional[float] = Field(default=None, ge=0)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = None
    pack_size: Optional[float] = Field(default=None, ge=1)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category_id: int
    category_name: str
    reference: Optional[str] = None
    unit_price: float
    quantity: float
    unit: str
    pack_size: float
    created_at: datetime


class ProductListOut(BaseModel):
    items: list[ProductOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProductStatsOut(BaseModel):
    total_products: int
    total_stock_quantity: float
    total_stock_value: float
    out_of_stock_count: int
    average_price: float


# ---------- Clients ----------

def _validate_phone(phone: Optional[str]) -> Optional[str]:
    if phone is None:
        return None
    phone = phone.strip()
    if not phone:
        return None
    if not phone.isdigit() or len(phone) != 9:
        raise ValueError("Le téléphone doit contenir exactement 9 chiffres")
    return phone


class ClientCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    address: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        return _validate_phone(v)


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        return _validate_phone(v)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: Optional[str] = None
    address: Optional[str] = None
    created_at: datetime


class ClientListOut(BaseModel):
    items: list[ClientOut]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------- Invoices ----------

class InvoiceLineCreate(BaseModel):
    product_id: int
    quantity: float
    unit_price: Optional[float] = Field(default=None, ge=0)


class InvoiceCreate(BaseModel):
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    note: Optional[str] = None
    lines: list[InvoiceLineCreate]


class InvoiceUpdate(BaseModel):
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    note: Optional[str] = None
    lines: list[InvoiceLineCreate]


class InvoiceLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: str
    quantity: float
    unit_price: float
    line_total: float


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    number: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    total: float
    note: Optional[str] = None
    created_at: datetime
    lines: list[InvoiceLineOut] = []
