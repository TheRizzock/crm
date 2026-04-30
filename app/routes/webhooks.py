import hmac
import hashlib
import base64
import json
import os
import time
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Activity, Contact

router = APIRouter()

STATUS_MAP = {
    "email.sent":      "sent",
    "email.delivered": "delivered",
    "email.bounced":   "bounced",
    "email.opened":    "opened",
    "email.clicked":   "clicked",
    "email.complained": "bounced",
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _verify_signature(body: bytes, headers) -> bool:
    secret = os.getenv("RESEND_WEBHOOK_SECRET", "")
    if not secret:
        return True  # no secret configured — skip (set it up in prod)

    svix_id        = headers.get("svix-id", "")
    svix_timestamp = headers.get("svix-timestamp", "")
    svix_signature = headers.get("svix-signature", "")

    if not (svix_id and svix_timestamp and svix_signature):
        return False

    try:
        if abs(time.time() - int(svix_timestamp)) > 300:
            return False
    except ValueError:
        return False

    signed = f"{svix_id}.{svix_timestamp}.{body.decode()}"
    raw    = secret[len("whsec_"):] if secret.startswith("whsec_") else secret
    key    = base64.b64decode(raw)
    mac    = hmac.new(key, signed.encode(), hashlib.sha256)
    computed = base64.b64encode(mac.digest()).decode()

    for sig in svix_signature.split(" "):
        if sig.startswith("v1,") and hmac.compare_digest(sig[3:], computed):
            return True
    return False


@router.post("/resend")
async def resend_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()

    if not _verify_signature(body, request.headers):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload    = json.loads(body)
    event_type = payload.get("type", "")
    status     = STATUS_MAP.get(event_type)

    if status is None:
        return {"ok": True}

    resend_id = payload.get("data", {}).get("email_id")
    if not resend_id:
        return {"ok": True}

    activity = db.query(Activity).filter(Activity.resend_id == resend_id).first()
    if activity:
        activity.status = status
        if status == "bounced" and activity.contact_id:
            contact = db.query(Contact).filter(Contact.id == activity.contact_id).first()
            if contact:
                contact.do_not_email = True
        db.commit()

    return {"ok": True}
