from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import ACCESS_TOKEN_EXPIRE_MINUTES
from ..auth import (
    create_access_token,
    authenticate_user,
    get_current_user,
    verify_password,
    get_password_hash,
)
from ..schemas import Token, UserMeResponse, UserPasswordChange

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserMeResponse)
async def read_users_me(current_user=Depends(get_current_user)):
    return current_user


@router.put("/me/password")
async def change_own_password(
    password_data: UserPasswordChange = Body(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный старый пароль",
        )
    if len(password_data.new_password) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль слишком короткий (минимум 4 символа)",
        )
    current_user.hashed_password = get_password_hash(password_data.new_password)
    db.commit()
    return {"success": True, "message": "Пароль успешно изменён"}
