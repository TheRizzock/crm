from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, exists, asc, desc
from datetime import datetime, timedelta, date
from typing import Optional
import math

from app.db import SessionLocal
from app.models import Contact, Activity, Company
from app.schemas import ContactSummary, ContactListResponse, ActivitySummary, ActivityCreate


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter()


@router.get("/count/today")
def count_activities_today(
    activity_type: Optional[str] = Query(None, description="email | linkedin | phone"),
    db: Session = Depends(get_db),
):
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)

    q = db.query(func.count(Activity.id)).filter(
        Activity.created_at >= today,
        Activity.created_at < tomorrow,
    )
    if activity_type:
        q = q.filter(Activity.type == activity_type)

    return {"count": q.scalar()}


@router.get("/", response_model=ContactListResponse)
def list_contacts(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    # date filters
    created_after: Optional[date] = None,
    created_before: Optional[date] = None,
    last_contacted_after: Optional[date] = None,
    last_contacted_before: Optional[date] = None,
    never_contacted: Optional[bool] = None,
    # attribute filters
    zb_status: Optional[str] = None,
    industry: Optional[str] = None,
    seniority_level: Optional[str] = None,
    activity_type: Optional[str] = Query(None, description="email | linkedin | phone"),
    # sorting
    sort_by: str = Query("created_at", pattern="^(created_at|last_contacted)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    last_act_sq = (
        db.query(
            Activity.contact_id,
            func.max(Activity.created_at).label("last_contacted_at"),
        )
        .group_by(Activity.contact_id)
        .subquery()
    )

    q = (
        db.query(Contact, Company.name.label("company_name"), last_act_sq.c.last_contacted_at)
        .outerjoin(last_act_sq, Contact.id == last_act_sq.c.contact_id)
        .outerjoin(Company, Contact.company_id == Company.id)
    )

    if created_after:
        q = q.filter(Contact.created_at >= created_after)
    if created_before:
        q = q.filter(Contact.created_at <= created_before)
    if last_contacted_after:
        q = q.filter(last_act_sq.c.last_contacted_at >= last_contacted_after)
    if last_contacted_before:
        q = q.filter(last_act_sq.c.last_contacted_at <= last_contacted_before)
    if never_contacted is True:
        q = q.filter(last_act_sq.c.last_contacted_at == None)
    if never_contacted is False:
        q = q.filter(last_act_sq.c.last_contacted_at != None)
    if zb_status:
        q = q.filter(Contact.zb_status == zb_status)
    if industry:
        q = q.filter(Contact.industry.ilike(f"%{industry}%"))
    if seniority_level:
        q = q.filter(Contact.seniority_level == seniority_level)
    if activity_type:
        q = q.filter(
            exists().where(
                (Activity.contact_id == Contact.id) & (Activity.type == activity_type)
            )
        )

    sort_col = (
        last_act_sq.c.last_contacted_at if sort_by == "last_contacted" else Contact.created_at
    )
    q = q.order_by(desc(sort_col) if sort_dir == "desc" else asc(sort_col))

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for contact, company_name, last_contacted_at in rows:
        items.append(ContactSummary(
            id=contact.id,
            first_name=contact.first_name,
            last_name=contact.last_name,
            email=contact.email,
            profile_url=contact.profile_url,
            mobile_number=contact.mobile_number,
            job_title=contact.job_title,
            headline=contact.headline,
            industry=contact.industry,
            seniority_level=contact.seniority_level,
            city=contact.city,
            state=contact.state,
            country=contact.country,
            zb_status=contact.zb_status,
            company_name=company_name,
            created_at=contact.created_at,
            last_contacted_at=last_contacted_at,
        ))

    return ContactListResponse(
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        items=items,
    )


@router.get("/{contact_id}/activities", response_model=list[ActivitySummary])
def get_contact_activities(contact_id: str, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    return (
        db.query(Activity)
        .filter(Activity.contact_id == contact_id)
        .order_by(desc(Activity.created_at))
        .all()
    )


@router.post("/{contact_id}/activities", response_model=ActivitySummary, status_code=201)
def create_activity(contact_id: str, payload: ActivityCreate, db: Session = Depends(get_db)):
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")

    activity = Activity(
        contact_id=contact_id,
        type=payload.type,
        subject=payload.subject,
        body=payload.body,
        status=payload.status,
        resend_id=payload.resend_id,
        created_at=payload.created_at or datetime.utcnow(),
    )
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity


@router.delete("/{contact_id}/activities/{activity_id}", status_code=204)
def delete_activity(contact_id: str, activity_id: str, db: Session = Depends(get_db)):
    activity = (
        db.query(Activity)
        .filter(Activity.id == activity_id, Activity.contact_id == contact_id)
        .first()
    )
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")

    db.delete(activity)
    db.commit()