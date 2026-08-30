from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import get_current_active_admin
from ..database import get_db
from ..models import User
from ..services.vpn_manager import VpnManager

router = APIRouter(prefix="/api/vpn", tags=["VPN Management"])

_vpn_manager = VpnManager()


class VpnUserCreate(BaseModel):
    username: str
    password: str
    ip_address: Optional[str] = "*"


@router.get("/users")
async def list_vpn_users(
    current_user: User = Depends(get_current_active_admin),
):
    try:
        users = _vpn_manager.list_users()
        return {"users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def add_vpn_user(
    user_data: VpnUserCreate = Body(...),
    current_user: User = Depends(get_current_active_admin),
):
    try:
        result = _vpn_manager.add_user(
            username=user_data.username,
            password=user_data.password,
            ip_address=user_data.ip_address or "*",
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to add user (user may already exist)",
            )
        return {"success": True, "message": "User added successfully"}
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
                detail="User not found or could not be removed",
            )
        return {"success": True, "message": "User removed successfully"}
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
                detail="Failed to restart VPN services",
            )
        return {"success": True, "message": "VPN services restarted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
