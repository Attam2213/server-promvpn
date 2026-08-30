from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..auth import get_current_active_admin
from ..models import Profile
from ..schemas import ProfileCreate, ProfileUpdate, ProfileResponse, ProfileWithRoutersResponse

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("", response_model=List[ProfileWithRoutersResponse])
def list_profiles(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    profiles = (
        db.query(Profile)
        .options(joinedload(Profile.routers))
        .order_by(Profile.created_at.desc())
        .all()
    )
    return profiles


@router.post("", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
def create_profile(
    profile_in: ProfileCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    profile = Profile(name=profile_in.name)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=ProfileWithRoutersResponse)
def get_profile(
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
    return profile


@router.put("/{profile_id}", response_model=ProfileResponse)
def update_profile(
    profile_id: int,
    profile_in: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_active_admin)
):
    profile = db.query(Profile).filter(Profile.id == profile_id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found"
        )
    profile.name = profile_in.name
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
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
    db.delete(profile)
    db.commit()
    return None
