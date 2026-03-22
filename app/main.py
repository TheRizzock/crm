from fastapi import FastAPI
from app.routes import lead

app = FastAPI()

app.include_router(lead.router, prefix="/lead")