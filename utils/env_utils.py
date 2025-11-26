import os
import logging


logger = logging.getLogger("env_utils")


def _mask(url: str) -> str:
    if not url:
        return ""
    # mask password between : and @
    try:
        prefix, rest = url.split('://', 1)
        if '@' in rest and ':' in rest.split('@', 1)[0]:
            user_pass, host_part = rest.split('@', 1)
            if ':' in user_pass:
                user, _ = user_pass.split(':', 1)
                return f"{prefix}://{user}:***@{host_part}"
        return url
    except Exception:
        return url


def get_database_url() -> str:
    """Resolve a usable DATABASE_URL with sensible fallbacks.

    Priority:
    1) DATABASE_PUBLIC_URL (works outside private network)
    2) DATABASE_URL
    3) CONFIG.database.url (if available)
    """
    db_public = os.getenv("DATABASE_PUBLIC_URL")
    if db_public:
        return db_public

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url

    try:
        from config import CONFIG  # type: ignore
        if getattr(CONFIG, "database", None) and getattr(CONFIG.database, "url", None):
            return CONFIG.database.url
    except Exception:
        pass

    raise RuntimeError("DATABASE_URL or DATABASE_PUBLIC_URL must be set")


def bootstrap_runtime_env() -> None:
    """Normalize env for cron/worker contexts so modules relying on DATABASE_URL don't crash.

    - Set DATABASE_URL from DATABASE_PUBLIC_URL if missing
    - If DATABASE_URL points to postgres.railway.internal and DATABASE_PUBLIC_URL exists, prefer PUBLIC
    - Log the effective URL (masked)
    """
    db_url = os.getenv("DATABASE_URL")
    db_public = os.getenv("DATABASE_PUBLIC_URL")

    if not db_url and db_public:
        os.environ["DATABASE_URL"] = db_public
        db_url = db_public

    if db_url and "postgres.railway.internal" in db_url and db_public:
        # prefer public in cron containers where private DNS isn't resolvable
        os.environ["DATABASE_URL"] = db_public
        db_url = db_public

    eff = _mask(db_url or "")
    logger.info(f"[env] Effective DATABASE_URL={eff}")
