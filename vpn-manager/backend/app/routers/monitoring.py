from fastapi import APIRouter, HTTPException, Query, Depends
from ..services.vpn_monitor import VpnMonitor
from ..database import SessionLocal
from ..auth import get_current_active_admin
from ..models import User

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

_monitor = VpnMonitor(db_session_factory=SessionLocal)


@router.get("/sessions")
async def get_sessions(_admin: User = Depends(get_current_active_admin)):
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
    _admin: User = Depends(get_current_active_admin),
):
    try:
        status = _monitor.get_router_status(router_id, vpn_username)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats(_admin: User = Depends(get_current_active_admin)):
    try:
        stats = _monitor.get_server_stats()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
