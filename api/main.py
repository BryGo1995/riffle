import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes.rivers import router as rivers_router

app = FastAPI(title="Riffle API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(rivers_router, prefix="/api/v1")
