import logging

logger = logging.getLogger("stratroom.db")


async def get_db():
    """Yield None — PostgreSQL has been replaced by MySQL bridge.

    All production data reads now use the MySQL bridge
    (app.services.java_bridge). This dependency stub is retained
    for routes that still type-hint db: AsyncSession = Depends(get_db).
    """
    yield None


async def check_db_health() -> bool:
    """Check MySQL connectivity via the bridge. Returns True if healthy."""
    try:
        from app.services.java_bridge import bridge
        await bridge.get(bridge.db_service, "/userList")
        return True
    except Exception:
        logger.exception("Database health check failed")
        return False
