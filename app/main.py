from fastapi import FastAPI
from app.routes import lead
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://oeeefeaddefcngbljhjcjmjlfgkloojn",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(lead.router, prefix="/lead")