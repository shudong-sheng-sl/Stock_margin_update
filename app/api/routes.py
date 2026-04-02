from fastapi import APIRouter, HTTPException

from app.models import MarginDashboardResponse
from app.services.stocks import clear_margin_dashboard_cache, get_margin_dashboard


router = APIRouter(tags=["stocks"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/margin-dashboard", response_model=MarginDashboardResponse)
async def margin_dashboard() -> MarginDashboardResponse:
    try:
        return get_margin_dashboard()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/margin-dashboard/clear-cache")
async def clear_margin_cache() -> dict[str, bool]:
    cleared = clear_margin_dashboard_cache()
    return {"cleared": cleared}
