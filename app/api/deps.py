"""Dependencias comunes para los endpoints."""
from app.database import get_db

# Re-export para uso conveniente
__all__ = ["get_db"]
