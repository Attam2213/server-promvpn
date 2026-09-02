from datetime import timedelta
import time
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, status, Body
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

_LOGIN_LOCK: dict = {}
_LOGIN_LOCK_LRU: list = []
_LOGIN_MAX_ATTEMPTS = 8
_LOGIN_WINDOW_SEC = 120
_LOGIN_COOLDOWN_SEC = 300
_LL_MU = threading.Lock()


def _check_login_throttle(remote_identifier: str) -> None:
    now = int(time.time())
    cutoff = now - _LOGIN_WINDOW_SEC
    with _LL_MU:
        for key in list(_LOGIN_LOCK.keys()):
            last_attempt_ts, attempts, locked_until = _LOGIN_LOCK[key]
            if last_attempt_ts < cutoff and locked_until < now:
                _LOGIN_LOCK.pop(key, None)
        entry = _LOGIN_LOCK.get(remote_identifier)
        if entry:
            _last_ts, attempts, locked_until = entry
            if locked_until and locked_until > now:
                left = locked_until - now
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Слишком много попыток. Повторите через {left} сек.",
                    headers={"Retry-After": str(left)},
                )
            attempts = attempts + 1
        else:
            attempts = 1
        if attempts >= _LOGIN_MAX_ATTEMPTS:
            locked = now + _LOGIN_COOLDOWN_SEC
            _LOGIN_LOCK[remote_identifier] = (now, attempts, locked)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Слишком много попыток входа. Блокировка на {_LOGIN_COOLDOWN_SEC} сек.",
                headers={"Retry-After": str(_LOGIN_COOLDOWN_SEC)},
            )
        _LOGIN_LOCK[remote_identifier] = (now, attempts, 0)


def _note_login_success(remote_identifier: str) -> None:
    with _LL_MU:
        _LOGIN_LOCK.pop(remote_identifier, None)


@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    request: Request = Depends(),
):
    try:
        remote = getattr(request, "client", None) or None
        remote = f"{remote.host}" if remote and hasattr(remote, "host") else "anon"
    except Exception:
        remote = "anon"
    throttle_key = f"{remote}:{form_data.username}".lower()
    _check_login_throttle(throttle_key)
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _note_login_success(throttle_key)
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
    new_pw = (password_data.new_password or "").strip()
    if len(new_pw) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль слишком короткий (минимум 10 символов, рекомендуется 12+ с цифрами и знаками)",
        )
    if len(set(new_pw)) < 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль слишком простой (используйте разные символы).",
        )
    current_user.hashed_password = get_password_hash(new_pw)
    db.commit()
    return {"success": True, "message": "Пароль успешно изменён"}

