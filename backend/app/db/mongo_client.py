# app/db/mongo_client.py
from __future__ import annotations
from functools import lru_cache
from pymongo import MongoClient
from app.settings import settings

@lru_cache(maxsize=1)
def get_client() -> MongoClient:
    return MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)

def get_db():
    return get_client()[settings.MONGODB_DB]
