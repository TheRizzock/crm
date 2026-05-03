from fastapi import APIRouter, Form, HTTPException, Depends
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import EmailCapture, ContactFormSubmission

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/contact")
async def contact(
    name: str = Form(...),
    email: str = Form(...),
    subject: str = Form("No subject"),
    message: str = Form(...),
    db: Session = Depends(get_db)
):
    try:
        db.add(ContactFormSubmission(name=name, email=email, subject=subject, message=message))
        db.commit()
        return {"success": True}
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="Failed to save submission")


@router.post("/collect")
async def collect(
    email: str = Form(...),
    resource: str = Form(...),
    db: Session = Depends(get_db)
):
    exists = db.query(EmailCapture).filter_by(email=email, resource=resource).first()
    if exists:
        return {"success": True}

    db.add(EmailCapture(email=email, resource=resource))
    db.commit()
    return {"success": True}