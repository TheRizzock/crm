from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db import Base
import uuid


def gen_id():
    return str(uuid.uuid4())


from sqlalchemy import Column, String, DateTime, ForeignKey
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

    contact = relationship("Contact", back_populates="company")


class Contact(Base):
    __tablename__ = "contact"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String)
    headline = Column(String)
    profile_url = Column(String, unique=True, index=True)

    company_id = Column(String, ForeignKey("company.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="contacts")
    activities = relationship("Activity", back_populates="contact")


class Activity(Base):
    __tablename__ = "activity"

    id = Column(String, primary_key=True, default=gen_id)
    contact_id = Column(String, ForeignKey("contact.id"))
    type = Column(String)  # optional but useful
    created_at = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact", back_populates="activities")


