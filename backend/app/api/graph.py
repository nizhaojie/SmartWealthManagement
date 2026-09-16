from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from neo4j import Driver
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_internal
from app.db.session import get_session
from app.http import ok
from app.knowledge_graph import service
from app.knowledge_graph.schemas import GraphSyncStatusResponse
from app.neo4j_client import get_neo4j
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/internal/graph")


@router.post("/rebuild")
def rebuild_graph(
    db: Session = Depends(get_session),
    driver: Driver = Depends(get_neo4j),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = service.rebuild(db, driver, namespace=settings.neo4j_graph_namespace, now=now)
    return ok(GraphSyncStatusResponse(**result).model_dump(mode="json"))


@router.get("/stats")
def get_graph_stats(
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    result = service.get_status(db)
    return ok(GraphSyncStatusResponse(**result).model_dump(mode="json"))
