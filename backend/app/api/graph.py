from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from neo4j import Driver
from sqlalchemy.orm import Session

from app import degradation
from app.agent.config import ADVISORY_CONFIG
from app.auth.dependencies import AuthContext, require_internal
from app.db.session import get_session
from app.http import ok
from app.knowledge_graph import graph_view, service
from app.knowledge_graph.schemas import CustomerGraphView, GraphSyncStatusResponse
from app.neo4j_client import get_neo4j
from app.settings import Settings, get_settings
from app.tracing import get_trace_id

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


@router.get("/customers/{customer_id}")
def get_customer_graph(
    customer_id: int,
    expand: str | None = None,
    driver: Driver = Depends(get_neo4j),
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    _auth: AuthContext = Depends(require_internal),
):
    expand_fund_managers = "fund_manager" in (expand or "").split(",")
    nodes, edges, degradation_reason = graph_view.customer_graph_degraded(
        driver,
        namespace=settings.neo4j_graph_namespace,
        customer_id=customer_id,
        expand_fund_managers=expand_fund_managers,
        timeout_seconds=settings.graph_view_timeout_seconds,
    )
    if degradation_reason is not None:
        # 界面拿到一张空图 + 降级标记，而这次降级进统计。
        degradation.record(
            db,
            dependency=degradation.DEPENDENCY_GRAPH,
            reason=degradation_reason,
            agent_type=ADVISORY_CONFIG.name,
            trace_id=get_trace_id(),
        )
    status = service.get_status(db)
    view = CustomerGraphView(
        customer_id=customer_id,
        nodes=nodes,
        edges=edges,
        synced_at=status["synced_at"],
        degraded=degradation_reason is not None,
    )
    return ok(view.model_dump(mode="json"))
