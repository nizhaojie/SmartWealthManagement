from fastapi import APIRouter

from app.health import probe_dependencies
from app.http import ok
from app.settings import get_settings

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    settings = get_settings()
    dependencies = probe_dependencies(settings)
    status = "ok" if all(item["ok"] for item in dependencies.values()) else "degraded"
    return ok(
        data={
            "status": status,
            "dependencies": dependencies,
            "llm_provider": settings.resolved_llm_provider,
        }
    )
