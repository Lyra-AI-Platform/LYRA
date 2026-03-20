"""
Lyra Memory API
Manage Lyra's long-term memory.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from lyra.memory.vector_memory import memory

router = APIRouter(prefix="/api/memory", tags=["memory"])


class StoreMemoryRequest(BaseModel):
    content: str
    memory_type: str = "user_fact"


class SearchMemoryRequest(BaseModel):
    query: str
    n_results: int = 5


@router.get("/stats")
async def memory_stats():
    return memory.get_stats()


@router.post("/store")
async def store_memory(request: StoreMemoryRequest):
    success = memory.store(request.content, request.memory_type)
    return {"success": success}


@router.post("/search")
async def search_memory(request: SearchMemoryRequest):
    results = memory.retrieve(request.query, request.n_results)
    return {"results": results, "count": len(results)}


@router.delete("/clear")
async def clear_memory():
    success = memory.clear()
    return {"success": success, "message": "All memories cleared" if success else "Failed"}
