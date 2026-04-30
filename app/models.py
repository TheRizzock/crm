from sqlalchemy import Column, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db import Base
import uuid


def gen_id():
    return str(uuid.uuid4())


class Company(Base):
    __tablename__ = "company"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, unique=True, index=True)
    profile_url = Column(String, unique=True)
    website = Column(String)
    company_size = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    # enrichment fields
    domain = Column(String)
    phone = Column(String)
    linkedin_uid = Column(String)
    founded_year = Column(String)
    annual_revenue = Column(String)
    annual_revenue_clean = Column(String)
    total_funding = Column(String)
    total_funding_clean = Column(String)
    description = Column(Text)
    keywords = Column(Text)
    technologies = Column(Text)
    street_address = Column(String)
    full_address = Column(String)
    city = Column(String)
    state = Column(String)
    country = Column(String)
    postal_code = Column(String)

    contacts = relationship("Contact", back_populates="company")


class Contact(Base):
    __tablename__ = "contact"

    id = Column(String, primary_key=True, default=gen_id)

    first_name = Column(String)
    last_name = Column(String)
    headline = Column(String)
    profile_url = Column(String, unique=True, index=True)

    # contact details
    email = Column(String, index=True)
    personal_email = Column(String)
    mobile_number = Column(String)
    job_title = Column(String)
    industry = Column(String)
    seniority_level = Column(String)
    functional_level = Column(String)
    city = Column(String)
    state = Column(String)
    country = Column(String)

    do_not_email = Column(Boolean, default=False)

    # zerobounce
    zb_status = Column(String)
    zb_sub_status = Column(String)
    zb_free_email = Column(String)
    zb_did_you_mean = Column(String)
    email_validated_at = Column(DateTime)

    company_id = Column(String, ForeignKey("company.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="contacts")
    activities = relationship("Activity", back_populates="contact")


class Activity(Base):
    __tablename__ = "activity"

    id = Column(String, primary_key=True, default=gen_id)
    contact_id = Column(String, ForeignKey("contact.id"))

    type = Column(String, index=True)    # email | linkedin | phone
    subject = Column(String)
    body = Column(Text)
    status = Column(String)              # sent | delivered | bounced | opened | clicked
    resend_id = Column(String)           # Resend message ID for webhook reconciliation

    created_at = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact", back_populates="activities")


class EmailCapture(Base):
    __tablename__ = "email_capture"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, index=True)
    resource = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


