"""Health-check feature module (blueprint)."""

from app.health.routes import health_bp

__all__ = ["health_bp"]
