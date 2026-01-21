# app/api/router.py
from fastapi import APIRouter
from app.api.routes.vidgenai import router as vidgenai_router

api_router = APIRouter()
api_router.include_router(vidgenai_router)
