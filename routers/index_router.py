from fastapi import APIRouter
from services import indexer

router = APIRouter()

@router.post("/start")
async def start_index():
    started = await indexer.start_indexing()
    if not started:
        return {"status": "already_running", "message": "Indexing is already in progress"}
    return {"status": "started"}

@router.get("/status")
def index_status():
    status = indexer.get_status()
    return {
        "is_running":         bool(status.get("is_running")),
        "started_at":         status.get("started_at"),
        "completed_at":       status.get("completed_at"),
        "processed_entries":  status.get("processed_entries", 0),
        "was_interrupted":    bool(status.get("was_interrupted")),
    }

@router.post("/interrupt")
async def interrupt_index():
    await indexer.interrupt_indexing()
    return {"status": "interrupted"}
