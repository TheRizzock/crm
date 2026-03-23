from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import Contact

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter()


@router.get("/count/today")
def count_contacts_today(db: Session = Depends(get_db)):
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)

    count = (
        db.query(func.count(Contact.id))
        .filter(Contact.created_at >= today)
        .filter(Contact.created_at < tomorrow)
        .scalar()
    )

    return {"count": count}