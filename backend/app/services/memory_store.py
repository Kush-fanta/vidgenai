# app/services/memory_store.py
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

class MemoryStore:
    def __init__(self):
        self._projects: Dict[str, Dict[str, Any]] = {}
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_project(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            pid = str(uuid4())
            ts = now_iso()
            d = dict(doc)
            d.update({"project_id": pid, "created_at": ts, "updated_at": ts})
            self._projects[pid] = d
            return d

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._projects.get(project_id)

    def update_project(self, project_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            d = self._projects.get(project_id)
            if not d:
                return None
            d.update(patch)
            d["updated_at"] = now_iso()
            return d

    def create_job(self, project_id: str, job_type: str) -> Dict[str, Any]:
        with self._lock:
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
            self._jobs[jid] = job
            return job

    def update_job(self, job_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return None
            j.update(patch)
            j["updated_at"] = now_iso()
            return j

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_latest_job_for_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j["project_id"] == project_id]
            if not jobs:
                return None
            jobs.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return jobs[0]

STORE = MemoryStore()
