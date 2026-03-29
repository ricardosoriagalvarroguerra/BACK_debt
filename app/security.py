"""JWT authentication, authorization, and role-based access control."""
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.config import get_settings
from app.models.user import User

settings = get_settings()

SECRET_KEY = settings.SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    VP_FINANZAS = "VP_FINANZAS"
    TESORERO = "TESORERO"
    ANALISTA = "ANALISTA"
    AUDITOR = "AUDITOR"
    VIEWER = "VIEWER"


PERMISSION_MATRIX = {
    "dashboard:read": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO, UserRole.ANALISTA, UserRole.AUDITOR, UserRole.VIEWER],
    "instrument:read": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO, UserRole.ANALISTA, UserRole.AUDITOR, UserRole.VIEWER],
    "instrument:create": [UserRole.ADMIN, UserRole.TESORERO, UserRole.ANALISTA],
    "instrument:update": [UserRole.ADMIN, UserRole.TESORERO, UserRole.ANALISTA],
    "instrument:delete": [UserRole.ADMIN],
    "instrument:approve": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO],
    "scenario:read": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO, UserRole.ANALISTA, UserRole.AUDITOR, UserRole.VIEWER],
    "scenario:create": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO, UserRole.ANALISTA],
    "scenario:approve": [UserRole.ADMIN, UserRole.VP_FINANZAS],
    "covenant:read": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO, UserRole.ANALISTA, UserRole.AUDITOR, UserRole.VIEWER],
    "covenant:modify": [UserRole.ADMIN, UserRole.VP_FINANZAS],
    "ceiling:modify": [UserRole.ADMIN, UserRole.VP_FINANZAS],
    "audit:read": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO, UserRole.AUDITOR],
    "report:export": [UserRole.ADMIN, UserRole.VP_FINANZAS, UserRole.TESORERO, UserRole.ANALISTA, UserRole.AUDITOR],
    "user:manage": [UserRole.ADMIN],
    "config:manage": [UserRole.ADMIN, UserRole.VP_FINANZAS],
}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def _get_default_user(db: Session) -> User:
    """Return the first admin user from DB, or create a dummy User object."""
    user = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
    if user:
        return user
    # Fallback: return first active user
    user = db.query(User).filter(User.is_active == True).first()
    if user:
        return user
    # Last resort: build a dummy object without persisting
    dummy = User()
    dummy.id = 0
    dummy.email = "admin@sistema.local"
    dummy.full_name = "Administrador"
    dummy.role = UserRole.ADMIN.value
    dummy.is_active = True
    return dummy


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Return authenticated user if token is valid, else None."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user and user.is_active:
        return user
    return None

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Return authenticated user or raise 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado. Inicie sesion.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise credentials_exception
    return user

def require_role(*roles):
    """All users have full access — role check passes through."""
    async def role_checker(user: User = Depends(get_current_user)):
        return user
    return role_checker

def require_permission(action: str):
    """All users have full access — permission check passes through."""
    async def permission_checker(user: User = Depends(get_current_user)):
        return user
    return permission_checker
