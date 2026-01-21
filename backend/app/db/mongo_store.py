# app/db/mongo_store.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4
from pymongo import ReturnDocument
from app.db.mongo_client import get_db

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

class MongoStore:
    def __init__(self):
        self._db = get_db()

    def create_project(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        pid = str(uuid4())
        ts = now_iso()
        d = dict(doc)
        d.update({"project_id": pid, "created_at": ts, "updated_at": ts})
        self._db.projects.insert_one(d)
        return d

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self._db.projects.find_one({"project_id": project_id}, {"_id": 0})

    def update_project(self, project_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = dict(patch)
        p["updated_at"] = now_iso()
        return self._db.projects.find_one_and_update(
            {"project_id": project_id},
            {"$set": p},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )

    def create_job(self, project_id: str, job_type: str) -> Dict[str, Any]:
        jid = str(uuid4())
        ts = now_iso()
        job = {
            "job_id": jid,
            "project_id": project_id,
            "type": job_type,
            "status": "queued",
            "stage": None,
            "progress": 0,
            "error": None,
            "result": {},
            "created_at": ts,
            "updated_at": ts,
        }
        self._db.jobs.insert_one(job)
        return job

    def update_job(self, job_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        p = dict(patch)
        p["updated_at"] = now_iso()
        return self._db.jobs.find_one_and_update(
            {"job_id": job_id},
            {"$set": p},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._db.jobs.find_one({"job_id": job_id}, {"_id": 0})

    def get_latest_job_for_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self._db.jobs.find_one(
            {"project_id": project_id},
            {"_id": 0},
            sort=[("created_at", -1)],
        )

STORE = MongoStore()
