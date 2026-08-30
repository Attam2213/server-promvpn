from fastapi import APIRouter, HTTPException, Query
from ..services.vpn_monitor import VpnMonitor

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

_monitor = VpnMonitor()


@router.get("/sessions")
async def get_sessions():
    try:
        sessions = _monitor.get_active_sessions()
        return {
            "count": len(sessions),
            "sessions": sessions,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/router/{router_id}")
async def get_router(
    router_id: int,
    vpn_username: str = Query(
        default="",
        description="VPN username для дополнительного поиска роутера",
    ),
):
    try:
        status = _monitor.get_router_status(router_id, vpn_username)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats():
    try:
        stats = _monitor.get_server_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
