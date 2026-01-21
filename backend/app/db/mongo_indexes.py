# app/db/mongo_indexes.py
from pymongo import ASCENDING, DESCENDING
from app.db.mongo_client import get_db

def ensure_indexes() -> None:
    db = get_db()
    db.projects.create_index([("project_id", ASCENDING)], unique=True)
    db.projects.create_index([("updated_at", DESCENDING)])
    db.jobs.create_index([("job_id", ASCENDING)], unique=True)
    db.jobs.create_index([("project_id", ASCENDING), ("created_at", DESCENDING)])
