# app/services/job_service.py
from __future__ import annotations

import threading
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from app.services.store import STORE
from app.pipelines.render import render_project_video


class JobService:
    def start_generate_video(self, project_id: str) -> str:
        job = STORE.create_job(project_id, job_type="generate_video")
        job_id = job["job_id"]
        threading.Thread(target=self._run_job, args=(job_id, project_id), daemon=True).start()
        return job_id

    def get_status_for_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return STORE.get_latest_job_for_project(project_id)

    def _run_job(self, job_id: str, project_id: str):
        try:
            STORE.update_job(job_id, {"status": "running", "stage": "starting", "progress": 1})

            proj = STORE.get_project(project_id)
            if not proj:
                STORE.update_job(job_id, {"status": "failed", "stage": "failed", "progress": 100, "error": "project_not_found"})
                return

            workdir = (Path("outputs/jobs") / job_id).resolve()
            workdir.mkdir(parents=True, exist_ok=True)

            STORE.update_job(job_id, {"stage": "render", "progress": 5})

            result = render_project_video(project=proj, workdir=str(workdir))
            # result contains urls + local paths
            STORE.update_job(job_id, {
                "status": "succeeded",
                "stage": "done",
                "progress": 100,
                "error": None,
                "result": result,
            })

            # update project pointers
            STORE.update_project(project_id, {
                "last_video_url": result.get("final_video_url"),
                "last_subtitle_url": result.get("subtitle_url"),
            })

        except Exception as e:
            print("\n[ERROR] Video generation failed:", e)
            traceback.print_exc()
            STORE.update_job(job_id, {"status": "failed", "stage": "failed", "progress": 100, "error": str(e), "result": {}})
