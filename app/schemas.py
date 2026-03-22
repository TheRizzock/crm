from pydantic import BaseModel


class LeadCreate(BaseModel):
    name: str
    headline: str
    company: str
    profileUrl: str