import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.models import Client, Invoice, InvoiceLine, Product, Shop, User
from app.schemas.schemas import InvoiceCreate, InvoiceOut

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _generate_invoice_number(db: Session, shop_id: int) -> str:
    count = db.query(Invoice).filter(Invoice.shop_id == shop_id).count()
    return f"FA{datetime.utcnow().strftime('%Y%m%d')}-{count + 1:04d}"


@router.get("", response_model=list[InvoiceOut])
def list_invoices(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return (
        db.query(Invoice)
        .options(joinedload(Invoice.lines))
        .filter(Invoice.shop_id == current_user.shop_id)
        .order_by(Invoice.id.desc())
        .all()
    )


@router.post("", response_model=InvoiceOut, status_code=201)
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not payload.lines:
        raise HTTPException(status_code=400, detail="La facture doit contenir au moins un article")

    if payload.client_id is not None:
        client = db.query(Client).filter(Client.id == payload.client_id, Client.shop_id == current_user.shop_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")

    invoice = Invoice(
        shop_id=current_user.shop_id,
        client_id=payload.client_id,
        number=_generate_invoice_number(db, current_user.shop_id),
        note=payload.note,
        total=0,
    )
    db.add(invoice)
    db.flush()

    total = 0.0
    for line in payload.lines:
        product = db.query(Product).filter(Product.id == line.product_id, Product.shop_id == current_user.shop_id).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Article {line.product_id} introuvable")
        if line.quantity <= 0:
            raise HTTPException(status_code=400, detail="La quantité doit être positive")
        if product.quantity < line.quantity:
            raise HTTPException(status_code=400, detail=f"Stock insuffisant pour {product.name}")

        product.quantity -= line.quantity
        line_total = product.unit_price * line.quantity
        total += line_total

        db.add(InvoiceLine(
            invoice_id=invoice.id,
            product_id=product.id,
            product_name=product.name,
            quantity=line.quantity,
            unit_price=product.unit_price,
            line_total=line_total,
        ))

    invoice.total = total
    db.commit()
    db.refresh(invoice)
    return invoice


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.lines))
        .filter(Invoice.id == invoice_id, Invoice.shop_id == current_user.shop_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    return invoice


@router.get("/{invoice_id}/pdf")
def get_invoice_pdf(invoice_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from pathlib import Path

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.styles import getSampleStyleSheet

    invoice = (
        db.query(Invoice)
        .options(joinedload(Invoice.lines))
        .filter(Invoice.id == invoice_id, Invoice.shop_id == current_user.shop_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")

    shop = db.query(Shop).filter(Shop.id == current_user.shop_id).first()
    client = db.query(Client).filter(Client.id == invoice.client_id).first() if invoice.client_id else None

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    styles = getSampleStyleSheet()
    elements = []

    if shop.logo_path and Path(shop.logo_path).exists():
        elements.append(Image(shop.logo_path, width=30 * mm, height=30 * mm, kind="proportional"))
        elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph(f"<b>{shop.name}</b>", styles["Title"]))
    if shop.address:
        elements.append(Paragraph(shop.address, styles["Normal"]))
    if shop.phone:
        elements.append(Paragraph(f"Tél: {shop.phone}", styles["Normal"]))
    elements.append(Spacer(1, 10 * mm))

    elements.append(Paragraph(f"<b>Facture N° {invoice.number}</b>", styles["Heading2"]))
    elements.append(Paragraph(f"Date: {invoice.created_at.strftime('%d/%m/%Y %H:%M')}", styles["Normal"]))
    if client:
        elements.append(Paragraph(f"Client: {client.name}" + (f" - {client.phone}" if client.phone else ""), styles["Normal"]))
    elements.append(Spacer(1, 6 * mm))

    data = [["Article", "Qté", "Prix unitaire", "Total"]]
    for line in invoice.lines:
        data.append([line.product_name, f"{line.quantity:g}", f"{line.unit_price:,.0f}", f"{line.line_total:,.0f}"])
    data.append(["", "", "Total", f"{invoice.total:,.0f} FCFA"])

    table = Table(data, colWidths=[80 * mm, 25 * mm, 35 * mm, 35 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f3f4f6")]),
    ]))
    elements.append(table)

    if invoice.note:
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph(f"Note: {invoice.note}", styles["Normal"]))

    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename=facture-{invoice.number}.pdf"},
    )
