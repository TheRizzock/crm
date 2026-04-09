from fastapi import FastAPI
from app.routes import lead
from app.routes import contacts
from app.routes import forms
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://oeeefeaddefcngbljhjcjmjlfgkloojn",
        "http://localhost:63343/",
        "https://dankowalsky.com",  # replace
        "https://www.dankowalsky.com"  # replace
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lead.router, prefix="/lead")
app.include_router(contacts.router, prefix="/contacts")
app.include_router(forms.router, prefix="/form")