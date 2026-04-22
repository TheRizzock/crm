import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc, func
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Company, Contact
from app.schemas import CompanyDetail, CompanyListResponse, CompanySummary


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


router = APIRouter()


@router.get("/", response_model=CompanyListResponse)
def list_companies(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = Query(None, description="Partial match on company name"),
    city: Optional[str] = None,
    state: Optional[str] = None,
    country: Optional[str] = None,
    sort_by: str = Query("name", pattern="^(name|created_at|contact_count)$"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    contact_count_sq = (
        db.query(Contact.company_id, func.count(Contact.id).label("contact_count"))
        .group_by(Contact.company_id)
        .subquery()
    )

    q = (
        db.query(Company, contact_count_sq.c.contact_count)
        .outerjoin(contact_count_sq, Company.id == contact_count_sq.c.company_id)
    )

    if search:
        q = q.filter(Company.name.ilike(f"%{search}%"))
    if city:
        q = q.filter(Company.city.ilike(f"%{city}%"))
    if state:
        q = q.filter(Company.state == state)
    if country:
        q = q.filter(Company.country == country)

    if sort_by == "contact_count":
        sort_col = contact_count_sq.c.contact_count
    elif sort_by == "created_at":
        sort_col = Company.created_at
    else:
        sort_col = Company.name

    q = q.order_by(desc(sort_col) if sort_dir == "desc" else asc(sort_col))

    total = q.count()
    rows  = q.offset((page - 1) * page_size).limit(page_size).all()

    items = [
        CompanySummary(
            id=company.id,
            name=company.name,
            website=company.website,
            domain=company.domain,
            company_size=company.company_size,
            city=company.city,
            state=company.state,
            country=company.country,
            annual_revenue_clean=company.annual_revenue_clean,
            industry=None,  # stored on contacts; omitted here for perf
            contact_count=count or 0,
            created_at=company.created_at,
        )
        for company, count in rows
    ]

    return CompanyListResponse(
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        items=items,
    )


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: str, db: Session = Depends(get_db)):
    contact_count = (
        db.query(func.count(Contact.id))
        .filter(Contact.company_id == company_id)
        .scalar()
    )

    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    return CompanyDetail(
        id=company.id,
        name=company.name,
        profile_url=company.profile_url,
        website=company.website,
        domain=company.domain,
        phone=company.phone,
        company_size=company.company_size,
        linkedin_uid=company.linkedin_uid,
        founded_year=company.founded_year,
        annual_revenue=company.annual_revenue,
        annual_revenue_clean=company.annual_revenue_clean,
        total_funding=company.total_funding,
        total_funding_clean=company.total_funding_clean,
        description=company.description,
        keywords=company.keywords,
        technologies=company.technologies,
        street_address=company.street_address,
        full_address=company.full_address,
        city=company.city,
        state=company.state,
        country=company.country,
        postal_code=company.postal_code,
        contact_count=contact_count,
        created_at=company.created_at,
    )
