from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Reports app + db connectivity. Used by uptime monitors and humans alike."""
    settings = get_settings()
    db_ok = False
    db_name = None
    try:
        result = await db.execute(text("SELECT current_database()"))
        db_name = result.scalar()
        db_ok = True
    except Exception as e:
        db_name = f"error: {e}"
    return {
        "app": settings.app_name,
        "environment": settings.environment,
        "version": "0.1.0",
        "db": db_name,
        "db_ok": db_ok,
    }
