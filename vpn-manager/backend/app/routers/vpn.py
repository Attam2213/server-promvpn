from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..auth import get_current_active_admin
from ..database import get_db
from ..models import User, Router
from ..services.vpn_manager import VpnManager

router = APIRouter(prefix="/api/vpn", tags=["VPN Management"])

_vpn_manager = VpnManager()


class VpnUserCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    username: str
    password: str
    ip_address: Optional[str] = "*"


class VpnUserUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")
    password: Optional[str] = None
    ip_address: Optional[str] = None
    username: Optional[str] = None


def _get_router_credentials_map(db: Session) -> dict:
    result = {}
    try:
        routers = db.query(Router).all()
        for r in routers:
            values = r.values or {}
            info = {
                "router_id": r.id,
                "router_name": r.name or values.get("routerName") or "",
            }
            for field in ("l2tpUser", "sstpUser", "pppoeUsername"):
                u = values.get(field)
                if u:
                    result[str(u).strip().lower()] = info
    except Exception:
        pass
    return result


@router.get("/users")
async def list_vpn_users(
    current_user: User = Depends(get_current_active_admin),
    db: Session = Depends(get_db),
):
    try:
        from ..services.vpn_monitor import VpnMonitor
        from ..database import SessionLocal
        monitor = VpnMonitor(db_session_factory=SessionLocal)
        sessions = monitor.get_active_sessions()
        online_users = {}
        for s in sessions:
            uname = (s.get("vpn_username") or "").strip().lower()
            if uname and s.get("online"):
                online_users[uname] = s
        users = _vpn_manager.list_users()
        router_map = _get_router_credentials_map(db)
        enriched = []
        for u in users:
            uname_lower = str(u.get("username") or "").strip().lower()
            info = router_map.get(uname_lower, {})
            sess = online_users.get(uname_lower)
            enriched.append({
                **u,
                "online": bool(sess),
                "router_id": info.get("router_id"),
                "router_name": info.get("router_name", ""),
                "protocol": sess.get("protocol") if sess else "",
                "ip_address_active": sess.get("ip_address") if sess else "",
                "interface": sess.get("interface") if sess else "",
                "uptime_human": sess.get("uptime_human") if sess else "",
                "traffic_human": sess.get("traffic_human") if sess else "0 B",
            })
        return {"users": enriched}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def add_vpn_user(
    user_data: VpnUserCreate = Body(...),
    current_user: User = Depends(get_current_active_admin),
):
    try:
        uname = (user_data.username or "").strip()
        pw = (user_data.password or "").strip()
        if not uname or not pw:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="username и password обязательны",
            )
        result = _vpn_manager.add_user(
            username=uname,
            password=pw,
            ip_address=(user_data.ip_address or "*").strip() or "*",
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось добавить пользователя (возможно уже существует)",
            )
        return {"success": True, "message": "Пользователь добавлен"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{username}")
async def update_vpn_user(
    username: str,
    user_data: VpnUserUpdate = Body(...),
    current_user: User = Depends(get_current_active_admin),
):
    try:
        existing_users = _vpn_manager.list_users()
        target = None
        for u in existing_users:
            if u["username"] == username:
                target = u
                break
        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден",
            )
        new_username = (user_data.username or username).strip() or username
        new_password = (user_data.password or "").strip() or target["password"]
        new_ip = (user_data.ip_address or target["ip_address"]).strip() or "*"

        removed = _vpn_manager.remove_user(username)
        if not removed:
            raise HTTPException(status_code=500, detail="Не удалось обновить пользователя")
        added = _vpn_manager.add_user(new_username, new_password, new_ip)
        if not added:
            raise HTTPException(status_code=500, detail="Не удалось добавить обновлённого пользователя")
        return {"success": True, "message": "Пользователь обновлён"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{username}")
async def remove_vpn_user(
    username: str,
    current_user: User = Depends(get_current_active_admin),
):
    try:
        result = _vpn_manager.remove_user(username)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден или не удалён",
            )
        return {"success": True, "message": "Пользователь удалён"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync")
async def sync_routers_to_vpn(
    current_user: User = Depends(get_current_active_admin),
    db: Session = Depends(get_db),
):
    try:
        result = _vpn_manager.sync_routers_to_vpn(db)
        return {
            "success": True,
            "added": result["added"],
            "removed": result["removed"],
            "skipped": result["skipped"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restart")
async def restart_vpn_services(
    current_user: User = Depends(get_current_active_admin),
):
    try:
        result = _vpn_manager.restart_services()
        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось перезапустить VPN службы",
            )
        return {"success": True, "message": "VPN службы перезапущены"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
