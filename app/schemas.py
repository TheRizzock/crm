from pydantic import BaseModel


class LeadCreate(BaseModel):
    first_name: str
    last_name: str
    headline: str
    company: str
    profileUrl: str