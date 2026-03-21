"""
Lyra AI Platform — Graph Knowledge API
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

REST endpoints for querying and managing the knowledge graph.
Supports Neo4j, NebulaGraph, ArangoDB, JanusGraph, Memgraph, and NetworkX.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from lyra.memory.graph_memory import graph_memory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/graph", tags=["graph"])


# ─── Request Models ───

class StoreEntityRequest(BaseModel):
    name: str
    entity_type: str = "Concept"
    description: str = ""
    source: str = ""


class StoreRelationRequest(BaseModel):
    from_entity: str
    relation: str
    to_entity: str
    weight: float = 1.0


class NeighborRequest(BaseModel):
    entity: str
    depth: int = 2
    relation_type: Optional[str] = None


class PathRequest(BaseModel):
    from_entity: str
    to_entity: str
    max_depth: int = 4


# ─── Endpoints ───

@router.get("/status")
async def graph_status():
    """Get graph database status, backend info, and node/edge counts."""
    stats = graph_memory.get_stats()
    return {
        "enabled": stats.get("enabled", True),
        "backend": stats.get("backend", "unknown"),
        "nodes": stats.get("nodes", 0),
        "edges": stats.get("edges", 0),
        "details": stats,
    }


@router.post("/entity")
async def store_entity(request: StoreEntityRequest):
    """Store or update an entity node in the knowledge graph."""
    graph_memory._init()
    node_id = graph_memory.backend.store_entity(
        name=request.name,
        entity_type=request.entity_type,
        properties={"description": request.description, "source": request.source},
    )
    return {"status": "stored", "node_id": node_id, "name": request.name}


@router.post("/relation")
async def store_relation(request: StoreRelationRequest):
    """Store a directed relationship between two entities."""
    graph_memory._init()
    ok = graph_memory.backend.store_relation(
        from_name=request.from_entity,
        relation=request.relation.upper().replace(" ", "_"),
        to_name=request.to_entity,
        properties={"weight": request.weight},
    )
    return {"status": "stored" if ok else "failed",
            "relation": f"{request.from_entity} -{request.relation}-> {request.to_entity}"}


@router.post("/neighbors")
async def get_neighbors(request: NeighborRequest):
    """Get neighboring entities in the graph up to N hops away."""
    graph_memory._init()
    neighbors = graph_memory.backend.get_neighbors(
        entity_name=request.entity,
        depth=min(request.depth, 4),
        relation_type=request.relation_type,
    )
    return {
        "entity": request.entity,
        "depth": request.depth,
        "neighbors": neighbors,
        "count": len(neighbors),
    }


@router.post("/path")
async def find_path(request: PathRequest):
    """Find the shortest path between two entities in the knowledge graph."""
    graph_memory._init()
    path = graph_memory.backend.find_path(
        from_name=request.from_entity,
        to_name=request.to_entity,
        max_depth=request.max_depth,
    )
    return {
        "from": request.from_entity,
        "to": request.to_entity,
        "path": path,
        "hops": len(path) - 1 if path else -1,
        "connected": len(path) > 0,
    }


@router.get("/search")
async def search_graph(q: str, limit: int = 10):
    """Search for entities in the knowledge graph by name or description."""
    graph_memory._init()
    results = graph_memory.backend.search_entities(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/context")
async def get_graph_context(query: str, hops: int = 2):
    """
    Get graph-enriched context for a query.
    Returns connected entity chains suitable for injecting into an AI prompt.
    """
    context = graph_memory.get_context_for_prompt(query, max_hops=hops)
    return {"query": query, "context": context, "has_context": bool(context)}


@router.get("/connections")
async def find_connections(from_entity: str, to_entity: str):
    """Find how two entities are connected through the knowledge graph."""
    result = graph_memory.find_connections(from_entity, to_entity)
    return {"result": result, "from": from_entity, "to": to_entity}
