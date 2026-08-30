from typing import List, Optional
import copy

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import get_current_active_admin
from ..models import Router, Profile
from ..schemas import RouterCreate, RouterUpdate, RouterResponse
from ..services.config_generator import ConfigGenerator

router = APIRouter(prefix="/api/profiles", tags=["routers"])
_values_config = ConfigGenerator()

def _normalize_values(values: dict) -> dict:
    if not values:
        return values or {}
    try:
        migrated = _values_config._apply_schema_defaults(copy.deepcopy(values))
        return migrated if isinstance(migrated, dict) else values
    except Exception:
        return values


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

    router = Router(
        profile_id=profile_id,
        name=name,
        values=values
    )
    db.add(router)
    db.commit()
    db.refresh(router)
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
    if router_in.name is not None:
        new_name = (router_in.name or "").strip() or router.name
        router.name = new_name
    if router_in.values is not None:
        router.values = _normalize_values(router_in.values or {})
    db.commit()
    db.refresh(router)
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
    db.delete(router)
    db.commit()
    return None
