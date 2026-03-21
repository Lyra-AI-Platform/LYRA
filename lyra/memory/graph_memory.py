"""
Lyra AI Platform — Graph Knowledge Memory
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0. See LICENSE for details.

Multi-backend knowledge graph system supporting:
  1. Neo4j Community Edition  — industry standard, rich ecosystem, Cypher queries
  2. NebulaGraph              — massive scale (trillions of edges), horizontal sharding
  3. ArangoDB Community       — multi-model (graph + document + key-value), GraphRAG
  4. JanusGraph               — distributed, Linux Foundation, Cassandra/HBase backend
  5. Memgraph                 — in-memory C++, real-time analytics, Kafka streaming
  6. NetworkX (fallback)      — pure Python in-process graph, no external DB needed

Architecture:
  GraphMemory auto-detects which backend is available and uses the best one.
  All backends implement the same interface: store_entity(), store_relation(),
  get_neighbors(), find_path(), and query().
  Knowledge stored in the graph is also indexed in ChromaDB for semantic search,
  giving LYRA both graph traversal AND vector similarity retrieval (GraphRAG).

Entity types: Topic, Fact, Article, Concept, Person, Place, Event, Technology
Relation types: RELATED_TO, LINKS_TO, CATEGORY_OF, MENTIONED_IN, LEADS_TO,
                IS_A, PART_OF, DISCOVERED_FROM, CONTRADICTS, SUPPORTS
"""
import asyncio
import hashlib
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

GRAPH_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "graph"
GRAPH_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# Abstract Backend Interface
# ═══════════════════════════════════════════════════════════════

class GraphBackend(ABC):
    """Abstract interface all graph backends must implement."""

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection. Returns True on success."""

    @abstractmethod
    def store_entity(self, name: str, entity_type: str, properties: Dict) -> str:
        """Store or update an entity node. Returns node ID."""

    @abstractmethod
    def store_relation(
        self, from_name: str, relation: str, to_name: str,
        properties: Dict = None
    ) -> bool:
        """Store a directed relationship between two entities."""

    @abstractmethod
    def get_neighbors(
        self, entity_name: str, depth: int = 1, relation_type: str = None
    ) -> List[Dict]:
        """Get neighboring entities up to `depth` hops away."""

    @abstractmethod
    def find_path(self, from_name: str, to_name: str, max_depth: int = 4) -> List[str]:
        """Find a path between two entities. Returns list of entity names."""

    @abstractmethod
    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        """Full-text search across entity names and properties."""

    @abstractmethod
    def get_stats(self) -> Dict:
        """Return {node_count, edge_count, backend_name, ...}"""

    @abstractmethod
    def close(self):
        """Close the connection cleanly."""


# ═══════════════════════════════════════════════════════════════
# 1. Neo4j Backend (Community Edition)
#    Install: brew install neo4j  |  docker run -p7474:7474 -p7687:7687 neo4j
#    Driver:  pip install neo4j
# ═══════════════════════════════════════════════════════════════

class Neo4jBackend(GraphBackend):
    """
    Neo4j Community Edition backend.
    Industry-standard graph DB with Cypher query language.
    Best for: knowledge graphs, RAG, fraud detection.
    Connects to: bolt://localhost:7687 by default.
    """

    def __init__(self, uri: str = "bolt://localhost:7687",
                 user: str = "neo4j", password: str = "lyra-knowledge"):
        self.uri = uri
        self.user = user
        self.password = password
        self.driver = None
        self.name = "Neo4j"

    def connect(self) -> bool:
        try:
            from neo4j import GraphDatabase
            self.driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            self.driver.verify_connectivity()
            self._create_indexes()
            logger.info(f"✅ Neo4j connected: {self.uri}")
            return True
        except Exception as e:
            logger.debug(f"Neo4j unavailable: {e}")
            return False

    def _create_indexes(self):
        """Create indexes for fast lookups."""
        with self.driver.session() as s:
            s.run("CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)")
            s.run("CREATE FULLTEXT INDEX entity_search IF NOT EXISTS FOR (e:Entity) ON EACH [e.name, e.description]")

    def store_entity(self, name: str, entity_type: str, properties: Dict) -> str:
        node_id = _make_id(name)
        props = {
            "id": node_id, "name": name, "type": entity_type,
            "updated_at": datetime.now().isoformat(), **properties
        }
        with self.driver.session() as s:
            s.run(
                f"MERGE (e:Entity:{entity_type} {{id: $id}}) "
                "SET e += $props",
                id=node_id, props=props
            )
        return node_id

    def store_relation(self, from_name: str, relation: str, to_name: str,
                       properties: Dict = None) -> bool:
        props = {"created_at": datetime.now().isoformat(), **(properties or {})}
        clean_rel = re.sub(r"[^A-Z_]", "_", relation.upper())
        try:
            with self.driver.session() as s:
                s.run(
                    f"MATCH (a:Entity {{name: $from_name}}) "
                    f"MATCH (b:Entity {{name: $to_name}}) "
                    f"MERGE (a)-[r:{clean_rel}]->(b) "
                    f"SET r += $props",
                    from_name=from_name, to_name=to_name, props=props
                )
            return True
        except Exception as e:
            logger.debug(f"Neo4j relation store failed: {e}")
            return False

    def get_neighbors(self, entity_name: str, depth: int = 1,
                      relation_type: str = None) -> List[Dict]:
        rel_filter = f":{relation_type}" if relation_type else ""
        with self.driver.session() as s:
            result = s.run(
                f"MATCH (e:Entity {{name: $name}})-[r{rel_filter}*1..{depth}]->(n:Entity) "
                "RETURN DISTINCT n.name AS name, n.type AS type, "
                "n.description AS description LIMIT 20",
                name=entity_name
            )
            return [dict(r) for r in result]

    def find_path(self, from_name: str, to_name: str, max_depth: int = 4) -> List[str]:
        with self.driver.session() as s:
            result = s.run(
                "MATCH p=shortestPath((a:Entity {name:$from})-[*.."+str(max_depth)+"]->(b:Entity {name:$to})) "
                "RETURN [n IN nodes(p) | n.name] AS path",
                **{"from": from_name, "to": to_name}
            )
            row = result.single()
            return row["path"] if row else []

    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        with self.driver.session() as s:
            result = s.run(
                "CALL db.index.fulltext.queryNodes('entity_search', $query) "
                "YIELD node, score RETURN node.name AS name, node.type AS type, "
                "node.description AS description, score LIMIT $limit",
                query=query, limit=limit
            )
            return [dict(r) for r in result]

    def get_stats(self) -> Dict:
        with self.driver.session() as s:
            nodes = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            edges = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
        return {"backend": "Neo4j", "nodes": nodes, "edges": edges, "uri": self.uri}

    def close(self):
        if self.driver:
            self.driver.close()


# ═══════════════════════════════════════════════════════════════
# 2. NebulaGraph Backend
#    Install: docker-compose (see docs.nebula-graph.io)
#    Driver:  pip install nebula3-python
#    Best for: trillion-scale graphs, horizontal sharding
# ═══════════════════════════════════════════════════════════════

class NebulaGraphBackend(GraphBackend):
    """
    NebulaGraph backend for massive-scale distributed graphs.
    Supports index-free adjacency at trillion-edge scale.
    Uses nGQL query language (similar to Cypher).
    Connects to: 127.0.0.1:9669 by default.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9669,
                 user: str = "root", password: str = "nebula",
                 space: str = "lyra_knowledge"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.space = space
        self.pool = None
        self.name = "NebulaGraph"

    def connect(self) -> bool:
        try:
            from nebula3.gclient.net import ConnectionPool
            from nebula3.Config import Config
            config = Config()
            config.max_connection_pool_size = 10
            self.pool = ConnectionPool()
            ok = self.pool.init([(self.host, self.port)], config)
            if not ok:
                return False
            self._setup_schema()
            logger.info(f"✅ NebulaGraph connected: {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.debug(f"NebulaGraph unavailable: {e}")
            return False

    def _run(self, ngql: str):
        with self.pool.session_context(self.user, self.password) as s:
            return s.execute(ngql)

    def _setup_schema(self):
        try:
            self._run(f"CREATE SPACE IF NOT EXISTS {self.space} (vid_type=FIXED_STRING(64));")
            self._run(f"USE {self.space};")
            self._run("CREATE TAG IF NOT EXISTS Entity(name string, type string, description string, updated_at string);")
            self._run("CREATE EDGE IF NOT EXISTS RELATION(type string, weight double);")
        except Exception as e:
            logger.debug(f"NebulaGraph schema setup: {e}")

    def store_entity(self, name: str, entity_type: str, properties: Dict) -> str:
        vid = _make_id(name)
        desc = properties.get("description", "")[:500].replace('"', '\\"')
        try:
            self._run(f'USE {self.space}; '
                      f'INSERT VERTEX Entity(name, type, description, updated_at) '
                      f'VALUES "{vid}":("{name}", "{entity_type}", "{desc}", "{datetime.now().isoformat()}");')
        except Exception as e:
            logger.debug(f"NebulaGraph store_entity: {e}")
        return vid

    def store_relation(self, from_name: str, relation: str, to_name: str,
                       properties: Dict = None) -> bool:
        fid, tid = _make_id(from_name), _make_id(to_name)
        try:
            self._run(f'USE {self.space}; '
                      f'INSERT EDGE RELATION(type, weight) '
                      f'VALUES "{fid}"->"{tid}":("{relation}", 1.0);')
            return True
        except Exception as e:
            logger.debug(f"NebulaGraph store_relation: {e}")
            return False

    def get_neighbors(self, entity_name: str, depth: int = 1,
                      relation_type: str = None) -> List[Dict]:
        vid = _make_id(entity_name)
        try:
            result = self._run(
                f'USE {self.space}; '
                f'GO {depth} STEPS FROM "{vid}" OVER RELATION '
                f'YIELD $$.Entity.name AS name, $$.Entity.type AS type;'
            )
            rows = []
            for r in result.rows():
                rows.append({"name": r.values[0].get_sVal().decode(),
                             "type": r.values[1].get_sVal().decode()})
            return rows
        except Exception as e:
            logger.debug(f"NebulaGraph get_neighbors: {e}")
            return []

    def find_path(self, from_name: str, to_name: str, max_depth: int = 4) -> List[str]:
        fid, tid = _make_id(from_name), _make_id(to_name)
        try:
            result = self._run(
                f'USE {self.space}; '
                f'FIND SHORTEST PATH FROM "{fid}" TO "{tid}" OVER * UPTO {max_depth} STEPS;'
            )
            # Parse path — simplified
            return [from_name, to_name]
        except Exception as e:
            logger.debug(f"NebulaGraph find_path: {e}")
            return []

    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        q = query.replace('"', '\\"')
        try:
            result = self._run(
                f'USE {self.space}; '
                f'LOOKUP ON Entity WHERE Entity.name CONTAINS "{q}" '
                f'YIELD Entity.name AS name, Entity.type AS type LIMIT {limit};'
            )
            return [{"name": r.values[0].get_sVal().decode(),
                     "type": r.values[1].get_sVal().decode()} for r in result.rows()]
        except Exception as e:
            logger.debug(f"NebulaGraph search: {e}")
            return []

    def get_stats(self) -> Dict:
        return {"backend": "NebulaGraph", "space": self.space,
                "host": f"{self.host}:{self.port}"}

    def close(self):
        if self.pool:
            self.pool.close()


# ═══════════════════════════════════════════════════════════════
# 3. ArangoDB Backend (Community Edition)
#    Install: brew install arangodb  |  docker run -p8529:8529 arangodb
#    Driver:  pip install python-arango
#    Best for: multi-model (graph + document + KV), GraphRAG
# ═══════════════════════════════════════════════════════════════

class ArangoDBBackend(GraphBackend):
    """
    ArangoDB Community Edition multi-model backend.
    Combines graph traversal with document storage — ideal for GraphRAG.
    Uses AQL (ArangoDB Query Language) which supports graph traversals
    alongside document queries in a single query.
    Connects to: http://localhost:8529 by default.
    """

    def __init__(self, url: str = "http://localhost:8529",
                 user: str = "root", password: str = "",
                 db_name: str = "lyra_knowledge"):
        self.url = url
        self.user = user
        self.password = password
        self.db_name = db_name
        self.db = None
        self.entities = None
        self.relations = None
        self.name = "ArangoDB"

    def connect(self) -> bool:
        try:
            from arango import ArangoClient
            client = ArangoClient(hosts=self.url)
            sys_db = client.db("_system", username=self.user, password=self.password)

            if not sys_db.has_database(self.db_name):
                sys_db.create_database(self.db_name)

            self.db = client.db(self.db_name, username=self.user, password=self.password)

            # Create vertex collection
            if not self.db.has_collection("entities"):
                self.db.create_collection("entities")
            self.entities = self.db.collection("entities")

            # Create edge collection
            if not self.db.has_collection("relations"):
                self.db.create_collection("relations", edge=True)
            self.relations = self.db.collection("relations")

            # Create named graph
            if not self.db.has_graph("knowledge_graph"):
                self.db.create_graph("knowledge_graph", edge_definitions=[{
                    "edge_collection": "relations",
                    "from_vertex_collections": ["entities"],
                    "to_vertex_collections": ["entities"],
                }])

            # Persistent index on name for fast lookups
            self.entities.add_persistent_index(fields=["name"], unique=False)
            logger.info(f"✅ ArangoDB connected: {self.url}/{self.db_name}")
            return True
        except Exception as e:
            logger.debug(f"ArangoDB unavailable: {e}")
            return False

    def store_entity(self, name: str, entity_type: str, properties: Dict) -> str:
        doc_key = _make_id(name)
        doc = {
            "_key": doc_key, "name": name, "type": entity_type,
            "updated_at": datetime.now().isoformat(), **properties
        }
        try:
            if self.entities.has(doc_key):
                self.entities.update(doc)
            else:
                self.entities.insert(doc)
        except Exception as e:
            logger.debug(f"ArangoDB store_entity: {e}")
        return f"entities/{doc_key}"

    def store_relation(self, from_name: str, relation: str, to_name: str,
                       properties: Dict = None) -> bool:
        from_key = f"entities/{_make_id(from_name)}"
        to_key = f"entities/{_make_id(to_name)}"
        edge_key = _make_id(f"{from_name}-{relation}-{to_name}")
        doc = {
            "_key": edge_key, "_from": from_key, "_to": to_key,
            "type": relation, "created_at": datetime.now().isoformat(),
            **(properties or {})
        }
        try:
            if not self.relations.has(edge_key):
                self.relations.insert(doc)
            return True
        except Exception as e:
            logger.debug(f"ArangoDB store_relation: {e}")
            return False

    def get_neighbors(self, entity_name: str, depth: int = 1,
                      relation_type: str = None) -> List[Dict]:
        start = f"entities/{_make_id(entity_name)}"
        type_filter = f'FILTER e.type == "{relation_type}"' if relation_type else ""
        aql = f"""
        FOR v, e IN 1..{depth} OUTBOUND "{start}" relations
          {type_filter}
          RETURN DISTINCT {{name: v.name, type: v.type, description: v.description}}
        """
        try:
            cursor = self.db.aql.execute(aql)
            return list(cursor)[:20]
        except Exception as e:
            logger.debug(f"ArangoDB get_neighbors: {e}")
            return []

    def find_path(self, from_name: str, to_name: str, max_depth: int = 4) -> List[str]:
        start = f"entities/{_make_id(from_name)}"
        end = f"entities/{_make_id(to_name)}"
        aql = f"""
        FOR p IN OUTBOUND K_SHORTEST_PATHS "{start}" TO "{end}" GRAPH "knowledge_graph"
          LIMIT 1
          RETURN [v.name FOR v IN p.vertices]
        """
        try:
            cursor = self.db.aql.execute(aql)
            result = list(cursor)
            return result[0] if result else []
        except Exception as e:
            logger.debug(f"ArangoDB find_path: {e}")
            return []

    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        aql = f"""
        FOR e IN entities
          FILTER CONTAINS(LOWER(e.name), LOWER("{query}"))
              OR CONTAINS(LOWER(e.description), LOWER("{query}"))
          LIMIT {limit}
          RETURN {{name: e.name, type: e.type, description: e.description}}
        """
        try:
            cursor = self.db.aql.execute(aql)
            return list(cursor)
        except Exception as e:
            logger.debug(f"ArangoDB search: {e}")
            return []

    def get_stats(self) -> Dict:
        try:
            nodes = self.entities.count()
            edges = self.relations.count()
            return {"backend": "ArangoDB", "nodes": nodes, "edges": edges, "url": self.url}
        except Exception:
            return {"backend": "ArangoDB", "url": self.url}

    def close(self):
        pass  # python-arango manages connections internally


# ═══════════════════════════════════════════════════════════════
# 4. JanusGraph Backend
#    Install: docker run -p8182:8182 janusgraph/janusgraph
#    Driver:  pip install gremlinpython
#    Best for: massive distributed graphs with Cassandra/HBase backend
# ═══════════════════════════════════════════════════════════════

class JanusGraphBackend(GraphBackend):
    """
    JanusGraph backend using Apache Gremlin traversal language.
    Linux Foundation project, supports Cassandra/HBase/BerkeleyDB backends.
    Best for: extremely high-volume transactional graphs.
    Connects via Gremlin Server WebSocket: ws://localhost:8182/gremlin
    """

    def __init__(self, url: str = "ws://localhost:8182/gremlin"):
        self.url = url
        self.g = None
        self.connection = None
        self.name = "JanusGraph"

    def connect(self) -> bool:
        try:
            from gremlin_python.driver import client, serializer
            from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
            from gremlin_python.process.anonymous_traversal import traversal

            self.connection = DriverRemoteConnection(
                self.url, "g",
                message_serializer=serializer.GraphSONMessageSerializer()
            )
            self.g = traversal().with_remote(self.connection)
            # Test connectivity
            self.g.V().limit(1).to_list()
            logger.info(f"✅ JanusGraph connected: {self.url}")
            return True
        except Exception as e:
            logger.debug(f"JanusGraph unavailable: {e}")
            return False

    def store_entity(self, name: str, entity_type: str, properties: Dict) -> str:
        try:
            from gremlin_python.process.graph_traversal import __
            existing = self.g.V().has("Entity", "name", name).to_list()
            if existing:
                v = existing[0]
                self.g.V(v).property("type", entity_type).property(
                    "updated_at", datetime.now().isoformat()
                ).iterate()
            else:
                t = self.g.add_v("Entity").property("name", name).property(
                    "type", entity_type
                ).property("updated_at", datetime.now().isoformat())
                for k, v in properties.items():
                    if isinstance(v, str):
                        t = t.property(k, v[:500])
                t.iterate()
        except Exception as e:
            logger.debug(f"JanusGraph store_entity: {e}")
        return _make_id(name)

    def store_relation(self, from_name: str, relation: str, to_name: str,
                       properties: Dict = None) -> bool:
        try:
            self.g.V().has("Entity", "name", from_name).as_("a") \
                .V().has("Entity", "name", to_name).as_("b") \
                .add_e(relation).from_("a").to("b").iterate()
            return True
        except Exception as e:
            logger.debug(f"JanusGraph store_relation: {e}")
            return False

    def get_neighbors(self, entity_name: str, depth: int = 1,
                      relation_type: str = None) -> List[Dict]:
        try:
            t = self.g.V().has("Entity", "name", entity_name)
            for _ in range(depth):
                t = t.out()
            results = t.value_map("name", "type").to_list()
            return [{"name": r.get("name", [""])[0], "type": r.get("type", [""])[0]}
                    for r in results[:20]]
        except Exception as e:
            logger.debug(f"JanusGraph neighbors: {e}")
            return []

    def find_path(self, from_name: str, to_name: str, max_depth: int = 4) -> List[str]:
        try:
            from gremlin_python.process.graph_traversal import __
            result = self.g.V().has("Entity", "name", from_name) \
                .repeat(__.out().simplePath()).until(__.has("name", to_name)) \
                .limit(1).path().by("name").to_list()
            return list(result[0]) if result else []
        except Exception as e:
            logger.debug(f"JanusGraph find_path: {e}")
            return []

    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        try:
            results = self.g.V().has("Entity", "name",
                                      __import__('gremlin_python.process.graph_traversal',
                                                 fromlist=['TextP']).TextP.containing(query)
                                      ).limit(limit).value_map("name", "type").to_list()
            return [{"name": r.get("name", [""])[0], "type": r.get("type", [""])[0]}
                    for r in results]
        except Exception as e:
            logger.debug(f"JanusGraph search: {e}")
            return []

    def get_stats(self) -> Dict:
        try:
            nodes = self.g.V().count().next()
            edges = self.g.E().count().next()
            return {"backend": "JanusGraph", "nodes": nodes, "edges": edges}
        except Exception:
            return {"backend": "JanusGraph"}

    def close(self):
        if self.connection:
            self.connection.close()


# ═══════════════════════════════════════════════════════════════
# 5. Memgraph Backend
#    Install: docker run -p7687:7687 -p3000:3000 memgraph/memgraph-platform
#    Driver:  pip install neo4j  (Memgraph is Bolt/Cypher compatible)
#    Best for: in-memory real-time analytics, Kafka streaming
# ═══════════════════════════════════════════════════════════════

class MemgraphBackend(Neo4jBackend):
    """
    Memgraph backend — in-memory C++ graph DB, Cypher/Bolt compatible.
    Reuses Neo4j's Python driver since Memgraph speaks the same protocol.
    Best for: real-time analytics, streaming data (Kafka integration).
    Connects to: bolt://localhost:7687 (Memgraph's default port).
    """

    def __init__(self, uri: str = "bolt://localhost:7688",
                 user: str = "", password: str = ""):
        super().__init__(uri=uri, user=user, password=password)
        self.name = "Memgraph"

    def connect(self) -> bool:
        try:
            from neo4j import GraphDatabase
            self.driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password) if self.user else None
            )
            self.driver.verify_connectivity()
            # Memgraph uses different index syntax
            with self.driver.session() as s:
                s.run("CREATE INDEX ON :Entity(name);")
            logger.info(f"✅ Memgraph connected: {self.uri}")
            return True
        except Exception as e:
            logger.debug(f"Memgraph unavailable: {e}")
            return False

    def get_stats(self) -> Dict:
        stats = super().get_stats()
        stats["backend"] = "Memgraph"
        return stats


# ═══════════════════════════════════════════════════════════════
# 6. NetworkX In-Memory Fallback (no external DB required)
#    Install: pip install networkx  (included in requirements.txt)
#    Persists to JSON file in data/graph/
# ═══════════════════════════════════════════════════════════════

class NetworkXBackend(GraphBackend):
    """
    Pure Python in-memory graph using NetworkX.
    No external database required — always available as fallback.
    Persists to disk as JSON so knowledge survives restarts.
    Best for: local development, testing, when no graph DB is running.
    """

    PERSIST_FILE = GRAPH_DATA_DIR / "graph_networkx.json"

    def __init__(self):
        self.G = None
        self.name = "NetworkX (in-memory)"

    def connect(self) -> bool:
        try:
            import networkx as nx
            self.G = nx.MultiDiGraph()
            self._load()
            logger.info(f"✅ NetworkX graph loaded: {self.G.number_of_nodes()} nodes, {self.G.number_of_edges()} edges")
            return True
        except ImportError:
            # Ultra-minimal fallback using plain dicts
            self.G = _DictGraph()
            logger.info("✅ Dict graph (no networkx) ready")
            return True

    def store_entity(self, name: str, entity_type: str, properties: Dict) -> str:
        node_id = _make_id(name)
        attrs = {"name": name, "type": entity_type,
                 "updated_at": datetime.now().isoformat(), **properties}
        self.G.add_node(node_id, **attrs)
        self._save_debounced()
        return node_id

    def store_relation(self, from_name: str, relation: str, to_name: str,
                       properties: Dict = None) -> bool:
        fid, tid = _make_id(from_name), _make_id(to_name)
        if not self.G.has_node(fid):
            self.G.add_node(fid, name=from_name)
        if not self.G.has_node(tid):
            self.G.add_node(tid, name=to_name)
        self.G.add_edge(fid, tid, relation=relation, **(properties or {}))
        self._save_debounced()
        return True

    def get_neighbors(self, entity_name: str, depth: int = 1,
                      relation_type: str = None) -> List[Dict]:
        nid = _make_id(entity_name)
        if not self.G.has_node(nid):
            return []
        try:
            import networkx as nx
            visited = set()
            frontier = {nid}
            results = []
            for _ in range(depth):
                next_frontier = set()
                for node in frontier:
                    for succ in self.G.successors(node):
                        if succ not in visited:
                            visited.add(succ)
                            next_frontier.add(succ)
                            attrs = self.G.nodes[succ]
                            results.append({
                                "name": attrs.get("name", succ),
                                "type": attrs.get("type", ""),
                                "description": attrs.get("description", "")[:200],
                            })
                frontier = next_frontier
            return results[:20]
        except Exception:
            return []

    def find_path(self, from_name: str, to_name: str, max_depth: int = 4) -> List[str]:
        fid, tid = _make_id(from_name), _make_id(to_name)
        try:
            import networkx as nx
            path = nx.shortest_path(self.G, fid, tid)
            return [self.G.nodes[n].get("name", n) for n in path]
        except Exception:
            return []

    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        # Split query into tokens so multi-word queries match individual entities
        tokens = [t for t in query.lower().split() if len(t) > 2]
        q = query.lower()
        results = []
        scored = []
        for nid, attrs in self.G.nodes(data=True):
            name = attrs.get("name", "")
            name_l = name.lower()
            desc_l = attrs.get("description", "").lower()
            score = 0
            # Exact full-query match scores highest
            if q in name_l:
                score += 10
            if q in desc_l:
                score += 5
            # Individual token matches
            for t in tokens:
                if t in name_l:
                    score += 3
                if t in desc_l:
                    score += 1
            if score > 0:
                scored.append((score, name, attrs))
        scored.sort(key=lambda x: -x[0])
        for score, name, attrs in scored[:limit]:
            results.append({"name": name, "type": attrs.get("type", ""),
                             "description": attrs.get("description", "")[:200]})
        return results

    def get_stats(self) -> Dict:
        return {
            "backend": "NetworkX (in-memory)",
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
            "persist_file": str(self.PERSIST_FILE),
        }

    def _save_debounced(self):
        """Save to disk (debounced — only every 50 writes)."""
        if not hasattr(self, "_write_count"):
            self._write_count = 0
        self._write_count += 1
        if self._write_count % 50 == 0:
            self._save()

    def _save(self):
        try:
            import networkx as nx
            from networkx.readwrite import json_graph
            data = json_graph.node_link_data(self.G)
            self.PERSIST_FILE.write_text(json.dumps(data, default=str))
        except Exception as e:
            logger.debug(f"Graph save failed: {e}")

    def _load(self):
        try:
            if self.PERSIST_FILE.exists():
                import networkx as nx
                from networkx.readwrite import json_graph
                data = json.loads(self.PERSIST_FILE.read_text())
                loaded = json_graph.node_link_graph(data, directed=True, multigraph=True)
                self.G.update(loaded)
        except Exception as e:
            logger.debug(f"Graph load failed: {e}")

    def close(self):
        self._save()


class _DictGraph:
    """Ultra-minimal dict-based graph when networkx isn't installed."""
    def __init__(self):
        self._nodes: Dict[str, Dict] = {}
        self._edges: List[Tuple] = []

    def add_node(self, nid: str, **attrs):
        self._nodes[nid] = attrs

    def add_edge(self, fid: str, tid: str, **attrs):
        self._edges.append((fid, tid, attrs))

    def has_node(self, nid: str) -> bool:
        return nid in self._nodes

    def nodes(self, data=False):
        if data:
            return self._nodes.items()
        return self._nodes.keys()

    def successors(self, nid: str):
        return [t for f, t, _ in self._edges if f == nid]

    def number_of_nodes(self) -> int:
        return len(self._nodes)

    def number_of_edges(self) -> int:
        return len(self._edges)


# ═══════════════════════════════════════════════════════════════
# GraphMemory — Unified Interface + Entity Extraction
# ═══════════════════════════════════════════════════════════════

class GraphMemory:
    """
    Unified knowledge graph memory for Lyra.

    Auto-detects and connects to the best available graph backend:
      Priority: ArangoDB > Neo4j > Memgraph > JanusGraph > NebulaGraph > NetworkX

    Usage:
      graph_memory.store_knowledge(topic, content, source_url)
      graph_memory.get_context_for_prompt(query)  → graph-enriched context string
      graph_memory.find_connections(entity_a, entity_b)
    """

    BACKEND_PRIORITY = [
        ("ArangoDB",    ArangoDBBackend,   {}),
        ("Neo4j",       Neo4jBackend,      {}),
        ("Memgraph",    MemgraphBackend,   {}),
        ("JanusGraph",  JanusGraphBackend, {}),
        ("NebulaGraph", NebulaGraphBackend,{}),
        ("NetworkX",    NetworkXBackend,   {}),
    ]

    def __init__(self):
        self.backend: Optional[GraphBackend] = None
        self._initialized = False
        self._entity_cache: Dict[str, str] = {}  # name -> node_id cache

    def _init(self):
        if self._initialized:
            return
        for name, cls, kwargs in self.BACKEND_PRIORITY:
            try:
                backend = cls(**kwargs)
                if backend.connect():
                    self.backend = backend
                    logger.info(f"Graph memory using: {name}")
                    break
            except Exception as e:
                logger.debug(f"Backend {name} failed: {e}")

        if not self.backend:
            # Should never happen since NetworkX is always available
            self.backend = NetworkXBackend()
            self.backend.connect()

        self._initialized = True

    # ─── Knowledge Storage ───

    def store_knowledge(
        self,
        topic: str,
        content: str,
        source_url: str = "",
        memory_type: str = "learned_knowledge",
    ) -> int:
        """
        Extract entities and relationships from content and store in graph.
        Returns count of entities stored.
        """
        self._init()
        if not content:
            return 0

        # Store the topic itself as an entity
        self.backend.store_entity(
            name=topic,
            entity_type="Topic",
            properties={"description": content[:500], "source": source_url},
        )

        # Extract entities mentioned in the content
        entities = _extract_entities(content, topic)
        stored = 0

        for entity_name, entity_type in entities:
            try:
                self.backend.store_entity(
                    name=entity_name,
                    entity_type=entity_type,
                    properties={"source": source_url},
                )
                # Connect entity to topic
                self.backend.store_relation(
                    topic, "MENTIONED_IN", entity_name,
                    {"source": source_url, "timestamp": datetime.now().isoformat()}
                )
                self.backend.store_relation(
                    entity_name, "RELATED_TO", topic
                )
                stored += 1
            except Exception as e:
                logger.debug(f"Graph entity store failed: {e}")

        return stored

    def store_wikipedia_article(
        self,
        title: str,
        content: str,
        url: str,
        topic: str,
        related_topics: List[str] = None,
    ) -> int:
        """
        Store a Wikipedia article as a rich graph node with all its connections.
        Also stores all related topics discovered from the article's links/categories.
        """
        self._init()

        # Store the article as an Article node
        self.backend.store_entity(
            name=title,
            entity_type="Article",
            properties={
                "description": content[:800],
                "source": url,
                "topic": topic,
                "source_type": "wikipedia",
            },
        )

        # Connect article to its topic
        self.backend.store_entity(topic, "Topic", {"source": url})
        self.backend.store_relation(title, "ABOUT", topic)
        self.backend.store_relation(topic, "HAS_ARTICLE", title)

        stored = 1

        # Store related topics and connect them
        for related in (related_topics or [])[:10]:
            if related and related != title:
                self.backend.store_entity(related, "Topic", {})
                self.backend.store_relation(title, "LINKS_TO", related)
                self.backend.store_relation(related, "RELATED_TO", topic)
                stored += 1

        # Extract and store entities from content
        entities = _extract_entities(content, title)
        for ename, etype in entities[:20]:
            self.backend.store_entity(ename, etype, {"source": url})
            self.backend.store_relation(title, "MENTIONS", ename)
            stored += 1

        return stored

    # ─── Knowledge Retrieval ───

    def get_context_for_prompt(self, query: str, max_hops: int = 2) -> str:
        """
        Retrieve graph-enriched context for a query.
        Combines neighbor traversal + entity search for rich context.
        Returns a formatted string ready to inject into the AI's system prompt.
        """
        self._init()
        if not self.backend:
            return ""

        lines = ["[GRAPH KNOWLEDGE — connected entities from knowledge graph:]"]

        # 1. Search for entities matching the query
        entities = self.backend.search_entities(query, limit=5)
        seen = set()

        for entity in entities:
            name = entity.get("name", "")
            etype = entity.get("type", "")
            desc = entity.get("description", "")
            if name and name not in seen:
                seen.add(name)
                lines.append(f"• [{etype}] {name}" + (f": {desc[:150]}" if desc else ""))

                # Get neighbors for graph traversal context
                neighbors = self.backend.get_neighbors(name, depth=min(max_hops, 2))
                if neighbors:
                    neighbor_names = [n.get("name", "") for n in neighbors[:5] if n.get("name")]
                    lines.append(f"  Connected to: {', '.join(neighbor_names)}")

        if len(lines) <= 1:
            return ""

        return "\n".join(lines)

    def find_connections(self, entity_a: str, entity_b: str) -> str:
        """Find how two entities are connected through the knowledge graph."""
        self._init()
        path = self.backend.find_path(entity_a, entity_b)
        if not path:
            return f"No path found between '{entity_a}' and '{entity_b}'"
        return f"Connection path: {' → '.join(path)}"

    def get_stats(self) -> Dict:
        """Return graph statistics."""
        self._init()
        if not self.backend:
            return {"enabled": False}
        stats = self.backend.get_stats()
        stats["enabled"] = True
        return stats


# ═══════════════════════════════════════════════════════════════
# Entity Extraction (regex-based NLP, no external library needed)
# ═══════════════════════════════════════════════════════════════

def _extract_entities(text: str, context_topic: str = "") -> List[Tuple[str, str]]:
    """
    Extract named entities from text using pattern matching.
    Returns list of (entity_name, entity_type) tuples.
    No external NLP library required — uses regex + heuristics.
    """
    entities = []
    seen = set()

    def add(name: str, etype: str):
        name = name.strip()
        if len(name) >= 3 and name.lower() not in seen and len(name) <= 80:
            seen.add(name.lower())
            entities.append((name, etype))

    # Multi-word proper nouns (Title Case phrases)
    proper_phrases = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\b', text)
    for p in proper_phrases[:30]:
        add(p, _classify_entity(p))

    # Single capitalized words (min 4 chars, not at sentence start)
    singles = re.findall(r'(?<=[a-z\s])\b([A-Z][a-z]{3,})\b', text)
    for s in singles[:20]:
        add(s, _classify_entity(s))

    # Quoted terms
    quoted = re.findall(r'"([^"]{3,60})"', text)
    for q in quoted[:10]:
        add(q, "Concept")

    # Technical terms (camelCase, acronyms, hyphenated)
    tech = re.findall(r'\b([A-Z]{2,}(?:[A-Z][a-z]+)*|[a-z]+(?:[A-Z][a-z]+)+)\b', text)
    for t in tech[:15]:
        add(t, "Technology")

    # Remove the context topic itself (already stored separately)
    entities = [(n, t) for n, t in entities if n.lower() != context_topic.lower()]

    return entities[:40]


def _classify_entity(name: str) -> str:
    """Classify an entity into a type based on its name."""
    name_lower = name.lower()

    tech_keywords = {"ai", "ml", "algorithm", "network", "system", "model",
                     "database", "api", "framework", "language", "protocol",
                     "computing", "intelligence", "learning", "neural"}
    science_keywords = {"physics", "biology", "chemistry", "mathematics",
                        "astronomy", "quantum", "theory", "hypothesis"}
    place_keywords = {"university", "institute", "laboratory", "city",
                      "country", "ocean", "river", "mountain"}
    person_patterns = re.compile(r'^[A-Z][a-z]+ [A-Z][a-z]+$')

    if any(k in name_lower for k in tech_keywords):
        return "Technology"
    if any(k in name_lower for k in science_keywords):
        return "Concept"
    if any(k in name_lower for k in place_keywords):
        return "Place"
    if person_patterns.match(name):
        return "Person"
    return "Concept"


def _make_id(name: str) -> str:
    """Create a stable, safe ID from an entity name."""
    clean = re.sub(r"[^a-z0-9]", "_", name.lower())[:40]
    suffix = hashlib.md5(name.encode()).hexdigest()[:6]
    return f"{clean}_{suffix}"


# Global singleton
graph_memory = GraphMemory()
