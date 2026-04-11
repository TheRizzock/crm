import os
from fastapi import APIRouter, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import resend
from dotenv import load_dotenv
from app.db import SessionLocal
from app.models import EmailCapture

load_dotenv()

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Allow your static site to hit this endpoint
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # tighten this later
#     allow_methods=["POST"],
#     allow_headers=["*"],
# )

resend.api_key = os.getenv("RESEND_API_KEY")


@router.post("/contact")
async def contact(
    name: str = Form(...),
    email: str = Form(...),
    subject: str = Form("No subject"),
    message: str = Form(...)
):
    try:
        html_content = f"""
        <h2>New Contact Form Submission</h2>
        <p><strong>Name:</strong> {name}</p>
        <p><strong>Email:</strong> {email}</p>
        <p><strong>Subject:</strong> {subject}</p>
        <p><strong>Message:</strong></p>
        <p>{message}</p>
        """

        resend.Emails.send({
            "from": "Portfolio Contact <dan@dankowalsky.com>",  # change later to your domain
            "to": ["dan@dankowalsky.com"],
            "subject": f"New Contact: {subject}",
            "html": html_content,
            "reply_to": email,  # clutch
        })

        return {"success": True}

    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail="Email failed to send")


@router.post("/collect")
async def collect(
    email: str = Form(...),
    resource: str = Form(...),
    db: Session = Depends(get_db)
):
    entry = EmailCapture(email=email, resource=resource)
    db.add(entry)
    db.commit()
    return {"success": True}