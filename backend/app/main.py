from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import cars, users

app = FastAPI(title="Laicai API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(cars.router, tags=["Cars"])
