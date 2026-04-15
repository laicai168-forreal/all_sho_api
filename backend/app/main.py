from fastapi import FastAPI
from app.routes import users

app = FastAPI(title="Laicai API", version="1.0.0")

app.include_router(users.router, prefix="/users", tags=["Users"])
