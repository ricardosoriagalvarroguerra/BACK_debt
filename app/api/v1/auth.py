"""Authentication endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.user import User
from app.security import verify_password, create_access_token, get_current_user, get_password_hash

router = APIRouter(prefix="/auth", tags=["Autenticación"])

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    role: str

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str | None
    role: str
    is_active: bool = True
    model_config = {"from_attributes": True}

@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Search by username or email
    user = (
        db.query(User)
        .filter(
            (User.username == form_data.username) | (User.email == form_data.username)
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=401, detail="Credenciales invalidas")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Usuario desactivado")
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="Contrasena no configurada. Contacte al administrador.")
    if not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales invalidas")
    # Update last login
    from datetime import datetime, timezone
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        role=user.role,
    )

@router.post("/refresh", response_model=TokenResponse)
def refresh_token(user: User = Depends(get_current_user)):
    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        role=user.role,
    )

@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(get_current_user)):
    return user


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(data: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cambiar contraseña del usuario actual."""
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="Contraseña no configurada")
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Contraseña actual incorrecta")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
    user.password_hash = get_password_hash(data.new_password)
    db.commit()
    return {"message": "Contraseña actualizada exitosamente"}


class SetPasswordRequest(BaseModel):
    email: str
    new_password: str


@router.post("/set-password")
def set_password(data: SetPasswordRequest, db: Session = Depends(get_db)):
    """Establecer contraseña inicial (solo si el usuario no tiene contraseña configurada)."""
    user = db.query(User).filter(User.email == data.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.password_hash:
        raise HTTPException(status_code=400, detail="El usuario ya tiene contraseña. Use cambiar contraseña.")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 8 caracteres")
    user.password_hash = get_password_hash(data.new_password)
    db.commit()
    return {"message": "Contraseña establecida exitosamente"}
