"""Admin & configuration endpoints."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.models.config import SystemConfig
from app.models.user import User
from app.security import get_current_user, require_permission

router = APIRouter(prefix="/admin", tags=["Administración"])

class ConfigUpdate(BaseModel):
    value: str
    description: Optional[str] = None

class UserCreate(BaseModel):
    username: Optional[str] = None
    email: str
    full_name: Optional[str] = None
    role: str = "ANALISTA"
    password: str

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

@router.get("/config")
def list_config(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("config:manage")),
):
    configs = db.query(SystemConfig).all()
    return [{"key": c.key, "value": c.value, "description": c.description} for c in configs]

@router.get("/config/{key}")
def get_config(
    key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("config:manage")),
):
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configuracion no encontrada")
    return {"key": config.key, "value": config.value, "description": config.description}

@router.put("/config/{key}")
def update_config(
    key: str,
    update: ConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("config:manage")),
):
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if config:
        config.value = update.value
        if update.description:
            config.description = update.description
    else:
        config = SystemConfig(key=key, value=update.value, description=update.description)
        db.add(config)
    db.commit()
    return {"key": key, "value": update.value}

@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("user:manage")),
):
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "email": u.email, "full_name": u.full_name, "role": u.role, "is_active": u.is_active} for u in users]

@router.post("/users", status_code=201)
def create_user(
    data: UserCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("user:manage")),
):
    from app.security import get_password_hash
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email")
    new_user = User(
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        role=data.role,
        password_hash=get_password_hash(data.password),
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"id": new_user.id, "username": new_user.username, "email": new_user.email, "full_name": new_user.full_name, "role": new_user.role, "is_active": new_user.is_active}

@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("user:manage")),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(target, field, value)
    db.commit()
    db.refresh(target)
    return {"id": target.id, "username": target.username, "email": target.email, "full_name": target.full_name, "role": target.role, "is_active": target.is_active}
