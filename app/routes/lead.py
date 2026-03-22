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
    print("PAYLOAD:", payload)

    try:
        company = db.query(models.Company).filter_by(name=payload.company).first()

        if not company:
            company = models.Company(name=payload.company)
            db.add(company)
            db.commit()
            db.refresh(company)

        existing = db.query(models.Contact).filter_by(profile_url=payload.profileUrl).first()

        if existing:
            return {"status": "exists"}

        contact = models.Contact(
            first_name=payload.first_name,
            last_name=payload.last_name,
            headline=payload.headline,
            profile_url=payload.profileUrl,
            company_id=company.id,
        )

        db.add(contact)
        db.commit()
        db.refresh(contact)

        print("CREATED:", contact.id)

        return {"status": "created"}

    except Exception as e:
        print("ERROR:", e)
        db.rollback()
        return {"status": "error", "detail": str(e)}