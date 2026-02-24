"""
Graph database service for BlackBox CTF Platform.

Uses Neo4j to store and query relationship data that is naturally
graph-shaped: challenge prerequisites, team solves, flag submissions
(for anti-cheat), and team membership events.

All operations are fire-and-forget — failures are logged as warnings and
never propagate to the caller, so Neo4j being unavailable does NOT affect
the existing MongoDB-backed functionality in any way.

Node types:
  (:Challenge)         – a CTF challenge
  (:Team)              – a competitor team
  (:User)              – an individual user
  (:FlagHash)          – a hashed flag value (SHA-256, never plaintext)

Edge types:
  (:Challenge)-[:REQUIRES]->(:Challenge)       – prerequisite
  (:Team|User)-[:SOLVED]->(:Challenge)         – correct solve
  (:Team|User)-[:SUBMITTED]->(:FlagHash)       – flag submission attempt
  (:User)-[:MEMBER_OF]->(:Team)                – team membership
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GraphService:
    """Thin, fault-tolerant wrapper around the Neo4j Python driver."""

    def __init__(self, uri: str, user: str, password: str):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None
        self._available = False
        self._connect()

    # ── Connection ────────────────────────────────────────────────────────────

    def _connect(self) -> None:
        try:
            from neo4j import GraphDatabase  # imported lazily so missing package is non-fatal
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self._driver.verify_connectivity()
            self._available = True
            logger.info("Neo4j graph service connected successfully at %s", self.uri)
        except ImportError:
            logger.warning(
                "neo4j package not installed — graph service disabled. "
                "Install it with: pip install neo4j>=5.0.0"
            )
        except Exception as exc:
            logger.warning(
                "Neo4j graph service unavailable (non-fatal, app continues normally): %s", exc
            )

    def is_available(self) -> bool:
        """Return True if the driver connected successfully."""
        return self._available

    def close(self) -> None:
        if self._driver:
            try:
                self._driver.close()
            except Exception:
                pass

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run(self, query: str, **params) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a Cypher query.  Returns a list of result dicts, or None if
        the service is unavailable or the query raised an exception.
        """
        if not self._available or not self._driver:
            return None
        try:
            with self._driver.session() as session:
                result = session.run(query, **params)
                return [record.data() for record in result]
        except Exception as exc:
            logger.warning("Neo4j query failed (non-fatal): %s", exc)
            return None

    # ── Challenge nodes & prerequisite edges ──────────────────────────────────

    def sync_challenge(self, challenge_id: str, name: str, category: str) -> None:
        """Upsert a Challenge node (called when a challenge is created/updated)."""
        self._run(
            "MERGE (c:Challenge {id: $id}) "
            "SET c.name = $name, c.category = $category",
            id=challenge_id, name=name, category=category,
        )

    def sync_prerequisite(self, challenge_id: str, requires_id: str) -> None:
        """
        Ensure a REQUIRES edge exists:
          (:Challenge {id: challenge_id})-[:REQUIRES]->(:Challenge {id: requires_id})
        Called whenever a prerequisite relationship is added in admin.
        """
        self._run(
            "MERGE (a:Challenge {id: $cid}) "
            "MERGE (b:Challenge {id: $rid}) "
            "MERGE (a)-[:REQUIRES]->(b)",
            cid=challenge_id, rid=requires_id,
        )

    def remove_prerequisite(self, challenge_id: str, requires_id: str) -> None:
        """Delete a REQUIRES edge (called when a prerequisite is removed)."""
        self._run(
            "MATCH (a:Challenge {id: $cid})-[r:REQUIRES]->(b:Challenge {id: $rid}) "
            "DELETE r",
            cid=challenge_id, rid=requires_id,
        )

    def get_solve_path(self, from_challenge_id: str, to_challenge_id: str) -> List[str]:
        """Return the shortest prerequisite chain between two challenges by name."""
        result = self._run(
            "MATCH path = shortestPath("
            "  (a:Challenge {id: $from_id})-[:REQUIRES*]->(b:Challenge {id: $to_id})"
            ") "
            "RETURN [n IN nodes(path) | n.name] AS path",
            from_id=from_challenge_id, to_id=to_challenge_id,
        )
        if result and result[0].get("path"):
            return result[0]["path"]
        return []

    # ── Team / User nodes ──────────────────────────────────────────────────────

    def sync_team(self, team_id: str, name: str) -> None:
        """Upsert a Team node."""
        self._run(
            "MERGE (t:Team {id: $id}) SET t.name = $name",
            id=team_id, name=name,
        )

    def sync_user(self, user_id: str, username: str) -> None:
        """Upsert a User node."""
        self._run(
            "MERGE (u:User {id: $id}) SET u.username = $username",
            id=user_id, username=username,
        )

    def record_team_join(self, user_id: str, username: str,
                         team_id: str, team_name: str) -> None:
        """
        Record that a user joined a team.
        Creates (or refreshes) a MEMBER_OF edge from User to Team.
        """
        self._run(
            "MERGE (u:User {id: $uid}) SET u.username = $uname "
            "MERGE (t:Team {id: $tid}) SET t.name = $tname "
            "MERGE (u)-[:MEMBER_OF {since: datetime()}]->(t)",
            uid=user_id, uname=username,
            tid=team_id, tname=team_name,
        )

    # ── Solve graph ───────────────────────────────────────────────────────────

    def record_solve(
        self,
        entity_id: str,
        challenge_id: str,
        challenge_name: str = "",
        challenge_category: str = "",
        is_team: bool = True,
        points: int = 0,
        is_first_blood: bool = False,
    ) -> None:
        """
        Record a correct solve as a SOLVED edge from Team (or User) to Challenge.
        The edge is merged so duplicate calls are idempotent.
        """
        label = "Team" if is_team else "User"
        self._run(
            f"MERGE (e:{label} {{id: $entity_id}}) "
            "MERGE (c:Challenge {id: $cid}) "
            "SET c.name = $cname, c.category = $cat "
            "MERGE (e)-[s:SOLVED]->(c) "
            "SET s.points = $points, s.first_blood = $first_blood, s.solved_at = datetime()",
            entity_id=entity_id, cid=challenge_id,
            cname=challenge_name, cat=challenge_category,
            points=points, first_blood=is_first_blood,
        )

    def get_unlocked_challenges(self, team_id: str) -> List[Dict]:
        """
        Return challenge dicts that a team can now access because all their
        REQUIRES prerequisites have been SOLVED.
        Useful for graph-aware unlock visualisation without re-hitting MongoDB.
        """
        result = self._run(
            "MATCH (t:Team {id: $tid})-[:SOLVED]->(solved:Challenge) "
            "WITH t, collect(solved) AS solved_list "
            "MATCH (next:Challenge)-[:REQUIRES]->(prereq:Challenge) "
            "WHERE prereq IN solved_list "
            "  AND NOT (t)-[:SOLVED]->(next) "
            "RETURN next.id AS challenge_id, next.name AS name, next.category AS category",
            tid=team_id,
        )
        return result or []

    def get_similar_teams(self, team_id: str, limit: int = 5) -> List[Dict]:
        """Return teams ranked by number of solve overlaps with the given team."""
        result = self._run(
            "MATCH (t:Team {id: $tid})-[:SOLVED]->(c:Challenge)<-[:SOLVED]-(other:Team) "
            "WHERE other.id <> $tid "
            "RETURN other.id AS team_id, other.name AS team_name, count(c) AS common_solves "
            "ORDER BY common_solves DESC "
            "LIMIT $limit",
            tid=team_id, limit=limit,
        )
        return result or []

    # ── Anti-cheat: submission graph ──────────────────────────────────────────

    @staticmethod
    def _hash_flag(flag: str) -> str:
        """SHA-256 hash of a flag value. Never stored in plaintext."""
        return hashlib.sha256((flag or "").encode()).hexdigest()

    def record_submission(
        self,
        entity_id: str,
        raw_flag: str,
        challenge_id: str,
        is_correct: bool,
        is_team: bool = True,
    ) -> None:
        """
        Record a flag submission attempt.
        The flag value is hashed (SHA-256) before being stored — plaintext
        flag values are never written to Neo4j.
        """
        label = "Team" if is_team else "User"
        flag_hash = self._hash_flag(raw_flag)
        self._run(
            f"MERGE (e:{label} {{id: $entity_id}}) "
            "MERGE (c:Challenge {id: $cid}) "
            "MERGE (f:FlagHash {hash: $flag_hash, challenge_id: $cid}) "
            "CREATE (e)-[:SUBMITTED {correct: $correct, ts: datetime()}]->(f)",
            entity_id=entity_id, cid=challenge_id,
            flag_hash=flag_hash, correct=is_correct,
        )

    def detect_flag_sharing(
        self, challenge_id: str, threshold: int = 2
    ) -> List[Dict]:
        """
        Find pairs of teams/users who submitted the same hashed flag for a challenge.
        Returns dicts with entity1, entity2, shared_flags count.
        threshold: minimum shared flag count to be considered suspicious.
        """
        result = self._run(
            "MATCH (e1)-[:SUBMITTED]->(f:FlagHash {challenge_id: $cid})"
            "<-[:SUBMITTED]-(e2) "
            "WHERE e1.id < e2.id "
            "WITH e1, e2, count(f) AS shared_flags "
            "WHERE shared_flags >= $threshold "
            "RETURN e1.id AS entity1, e2.id AS entity2, shared_flags "
            "ORDER BY shared_flags DESC",
            cid=challenge_id, threshold=threshold,
        )
        return result or []


# ── Flask integration ─────────────────────────────────────────────────────────

def init_graph(app) -> Optional[GraphService]:
    """
    Initialise the GraphService and attach it to the Flask app as ``app.graph``.

    If Neo4j is disabled (NEO4J_ENABLED=false) or unavailable, ``app.graph``
    is set to None and the rest of the app continues working normally.
    """
    if not app.config.get("NEO4J_ENABLED", True):
        app.graph = None
        app.logger.info("Neo4j graph service disabled via NEO4J_ENABLED=false")
        return None

    try:
        graph = GraphService(
            uri=app.config["NEO4J_URI"],
            user=app.config["NEO4J_USER"],
            password=app.config["NEO4J_PASSWORD"],
        )
        app.graph = graph
        return graph
    except Exception as exc:
        app.logger.warning("Could not initialise Neo4j graph service (non-fatal): %s", exc)
        app.graph = None
        return None
