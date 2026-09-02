from typing import List, Optional, Set
import copy

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_active_admin
from ..models import Router, Profile
from ..schemas import RouterCreate, RouterUpdate, RouterResponse
from ..services.config_generator import ConfigGenerator
from ..services.vpn_manager import VpnManager

router = APIRouter(prefix="/api/profiles", tags=["routers"])
_values_config = ConfigGenerator()
_vpn_manager = VpnManager()

def _normalize_values(values: dict) -> dict:
    if not values:
        return values or {}
    try:
        migrated = _values_config._apply_schema_defaults(copy.deepcopy(values))
        return migrated if isinstance(migrated, dict) else values
    except Exception:
        return values


def _collect_router_vpn_users(values: dict) -> Set[str]:
    users: Set[str] = set()
    if not values:
        return users
    for key in ("l2tpUser", "sstpUser", "pppoeUsername"):
        u = (values.get(key) or "").strip()
        if u:
            users.add(u)
    return users


def _validate_router_unique(db: Session, profile_id: int, values: dict, exclude_router_id: Optional[int] = None):
    errors = {}
    values = values or {}
    lan = values.get("lanOctet")
    if lan is not None:
        if isinstance(lan, str) and lan.isdigit():
            lan = int(lan)
        if not isinstance(lan, int) or lan < 1 or lan > 254:
            errors["lanOctet"] = "lanOctet должен быть целым числом 1–254."
    if not errors:
        same_lan = (
            db.query(Router)
            .filter(Router.profile_id == profile_id, Router.id != (exclude_router_id or -1))
            .all()
        )
        for r in same_lan:
            v = r.values or {}
            other_lan = v.get("lanOctet")
            if other_lan == lan:
                errors["lanOctet"] = (
                    f"lanOctet={lan} уже используется роутером #{r.id} «{r.name}»."
                )
                break

    router_users = _collect_router_vpn_users(values)
    if router_users:
        all_routers = (
            db.query(Router)
            .filter(Router.id != (exclude_router_id or -1))
            .all()
        )
        used_by: dict = {}
        for r in all_routers:
            for u in _collect_router_vpn_users(r.values or {}):
                if u in router_users:
                    used_by.setdefault(u, []).append(f"#{r.id} «{r.name}»")
        for u, where in used_by.items():
            errors[u] = f"VPN логин `{u}` уже используется: {', '.join(where)}."

    if errors:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Найдены конфликты уникальности роутера.", "errors": errors},
        )


def _remove_single_use_vpn_users(db: Session, vpn_mgr: VpnManager, users_to_remove: Set[str]):
    if not users_to_remove:
        return
    all_routers = db.query(Router).all()
    still_used: Set[str] = set()
    for r in all_routers:
        for u in _collect_router_vpn_users(r.values or {}):
            if u in users_to_remove:
                still_used.add(u)
    gone = users_to_remove - still_used
    for u in gone:
        try:
            vpn_mgr.remove_user(u)
        except Exception:
            pass


@router.get("/{profile_id}/routers", response_model=List[RouterResponse])
def list_routers(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    routers = db.query(Router).filter(Router.profile_id == profile_id).order_by(Router.created_at.desc()).all()
    return routers


@router.post("/{profile_id}/routers", response_model=RouterResponse, status_code=status.HTTP_201_CREATED)
def create_router(
    profile_id: int,
    router_in: RouterCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )

    name = (router_in.name or "").strip() or "Новый MikroTik"
    values = _normalize_values(router_in.values or {})
    _validate_router_unique(db, profile_id, values)

    router = Router(
        profile_id=profile_id,
        name=name,
        values=values
    )
    db.add(router)
    db.commit()
    db.refresh(router)
    try:
        _vpn_manager.sync_routers_to_vpn(db)
    except Exception:
        pass
    return router


@router.get("/{profile_id}/routers/{router_id}", response_model=RouterResponse)
def get_router(
    profile_id: int,
    router_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    router = db.query(Router).filter(
        Router.id == router_id,
        Router.profile_id == profile_id
    ).first()
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found"
        )
    return router


@router.put("/{profile_id}/routers/{router_id}", response_model=RouterResponse)
def update_router(
    profile_id: int,
    router_id: int,
    router_in: RouterUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    router = db.query(Router).filter(
        Router.id == router_id,
        Router.profile_id == profile_id
    ).first()
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found"
        )
    old_values = copy.deepcopy(router.values or {})
    old_users = _collect_router_vpn_users(old_values)
    if router_in.name is not None:
        new_name = (router_in.name or "").strip() or router.name
        router.name = new_name
    if router_in.values is not None:
        new_values = _normalize_values(router_in.values or {})
        _validate_router_unique(db, profile_id, new_values, exclude_router_id=router.id)
        router.values = new_values
    db.commit()
    db.refresh(router)
    try:
        new_users = _collect_router_vpn_users(router.values or {})
        removed_users = old_users - new_users
        if removed_users:
            _remove_single_use_vpn_users(db, _vpn_manager, removed_users)
        _vpn_manager.sync_routers_to_vpn(db)
    except Exception:
        pass
    return router


@router.delete("/{profile_id}/routers/{router_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_router(
    profile_id: int,
    router_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    router = db.query(Router).filter(
        Router.id == router_id,
        Router.profile_id == profile_id
    ).first()
    if not router:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Router not found"
        )
    router_users = _collect_router_vpn_users(router.values or {})
    db.delete(router)
    db.commit()
    try:
        if router_users:
            _remove_single_use_vpn_users(db, _vpn_manager, router_users)
        _vpn_manager.sync_routers_to_vpn(db)
    except Exception:
        pass
    return None
