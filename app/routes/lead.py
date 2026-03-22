from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app import models, schemas

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
def create_lead(payload: schemas.LeadCreate, db: Session = Depends(get_db)):

    # get or create company
    company = db.query(models.Company).filter_by(name=payload.company).first()

    if not company:
        company = models.Company(name=payload.company)
        db.add(company)
        db.commit()
        db.refresh(company)

    # dedupe contact
    existing = db.query(models.Contact).filter_by(profile_url=payload.profileUrl).first()

    if existing:
        return {"status": "exists"}

    contact = models.Contact(
        name=payload.name,
        headline=payload.headline,
        profile_url=payload.profileUrl,
        company_id=company.id,
    )

    db.add(contact)
    db.commit()

    return {"status": "created"}