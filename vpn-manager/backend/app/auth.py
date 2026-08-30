import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from .database import get_db
from .models import User
from .schemas import TokenData

def _build_crypt_context():
    candidates = []
    preferred = os.environ.get("PASSLIB_SCHEME", "").strip().lower()
    if preferred:
        candidates.append(preferred)
    candidates.extend(["bcrypt", "sha256_crypt"])

    working_schemes = []
    for scheme in candidates:
        if scheme in working_schemes:
            continue
        try:
            probe = CryptContext(schemes=[scheme], deprecated="auto")
            h = probe.hash("probe_pass")
            if probe.verify("probe_pass", h):
                working_schemes.append(scheme)
                print(f"[+] passlib scheme OK: {scheme}")
        except Exception as e:
            print(f"[!] passlib scheme SKIPPED {scheme}: {e}")

    if not working_schemes:
        print(f"[!] All schemes failed, force fallback to sha256_crypt without optional backends")
        working_schemes = ["sha256_crypt"]

    try:
        ctx = CryptContext(schemes=working_schemes, deprecated="auto")
        test_hash = ctx.hash("selftest")
        if ctx.verify("selftest", test_hash):
            return ctx
    except Exception as e:
        print(f"[!] CryptContext combined failed: {e}")
    return CryptContext(schemes=["sha256_crypt"], deprecated="auto")

pwd_context = _build_crypt_context()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"[!] verify_password error: {e}")
        return False


def get_password_hash(password: str) -> str:
    try:
        return pwd_context.hash(password)
    except ValueError as ve:
        if "longer than 72 bytes" in str(ve) or "truncate" in str(ve):
            print(f"[!] bcrypt 72-byte limit hit, fallback to sha256_crypt for long password: {ve}")
            ctx = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
            return ctx.hash(password)
        raise
    except Exception as e:
        print(f"[!] get_password_hash fallback: {e}")
        ctx = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
        return ctx.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_user(db: Session, username: str) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = get_user(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = get_user(db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user
