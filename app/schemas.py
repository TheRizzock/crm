from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class LeadCreate(BaseModel):
    first_name: str
    last_name: str
    headline: str
    company: str
    profileUrl: str


class ContactSummary(BaseModel):
    id: str
    first_name: Optional[str]
    last_name: Optional[str]
    email: Optional[str]
    mobile_number: Optional[str]
    profile_url: Optional[str]
    job_title: Optional[str]
    headline: Optional[str]
    industry: Optional[str]
    seniority_level: Optional[str]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    zb_status: Optional[str]
    company_name: Optional[str]
    created_at: Optional[datetime]
    last_contacted_at: Optional[datetime]

    model_config = {"from_attributes": True}


class ContactListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    items: list[ContactSummary]


class CompanySummary(BaseModel):
    id: str
    name: Optional[str]
    website: Optional[str]
    domain: Optional[str]
    company_size: Optional[str]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    annual_revenue_clean: Optional[str]
    industry: Optional[str]
    contact_count: Optional[int]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class CompanyDetail(BaseModel):
    id: str
    name: Optional[str]
    profile_url: Optional[str]
    website: Optional[str]
    domain: Optional[str]
    phone: Optional[str]
    company_size: Optional[str]
    linkedin_uid: Optional[str]
    founded_year: Optional[str]
    annual_revenue: Optional[str]
    annual_revenue_clean: Optional[str]
    total_funding: Optional[str]
    total_funding_clean: Optional[str]
    description: Optional[str]
    keywords: Optional[str]
    technologies: Optional[str]
    street_address: Optional[str]
    full_address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    postal_code: Optional[str]
    contact_count: Optional[int]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class CompanyListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    items: list[CompanySummary]


class ActivityCreate(BaseModel):
    type: str
    subject: Optional[str] = None
    body: Optional[str] = None
    status: Optional[str] = None
    resend_id: Optional[str] = None
    created_at: Optional[datetime] = None


class ActivitySummary(BaseModel):
    id: str
    type: Optional[str]
    subject: Optional[str]
    body: Optional[str]
    status: Optional[str]
    resend_id: Optional[str]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}