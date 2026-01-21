# app/services/store.py
from app.settings import settings

if settings.STORE_BACKEND == "mongo":
    from app.db.mongo_store import STORE  # type: ignore
else:
    from app.services.memory_store import STORE  # type: ignore
