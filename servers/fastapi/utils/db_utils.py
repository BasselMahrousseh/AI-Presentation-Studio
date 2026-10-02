import os
from pathlib import Path
from urllib.parse import urlsplit
import ssl

from sqlalchemy.engine import URL, make_url

from utils.get_env import get_app_data_directory_env, get_database_url_env


def _persistence_mode() -> str:
    mode = os.getenv("PERSISTENCE_MODE", "").strip().lower()
    adapter = os.getenv("DATABASE_ADAPTER", "").strip().lower()
    if mode not in {"", "sqlite", "oracle"}:
        raise ValueError("Studio PERSISTENCE_MODE must be sqlite or oracle")
    if adapter not in {"", "sqlite", "oracle"}:
        raise ValueError("Studio DATABASE_ADAPTER must be sqlite or oracle")
    if mode == "oracle" or adapter == "oracle":
        return "oracle"
    return mode


def database_is_configured() -> bool:
    return bool(
        _persistence_mode() == "oracle"
        or (get_database_url_env() or "").strip()
        or (get_app_data_directory_env() or "").strip()
    )


def build_oracle_dsn() -> str:
    """Easy Connect / descriptor for ORACLE_DSN, or HOST + PORT + SERVICE_NAME."""
    explicit = (os.getenv("ORACLE_DSN") or "").strip()
    if explicit:
        return explicit
    host = (os.getenv("ORACLE_HOST") or "").strip()
    service = (os.getenv("ORACLE_SERVICE_NAME") or "").strip()
    if not host or not service:
        return ""
    port = (os.getenv("ORACLE_PORT") or "1521").strip()
    protocol = (os.getenv("ORACLE_PROTOCOL") or "tcp").strip().lower() or "tcp"
    return (
        "(DESCRIPTION=(CONNECT_TIMEOUT=20)"
        f"(ADDRESS=(PROTOCOL={protocol})(HOST={host})(PORT={port}))"
        f"(CONNECT_DATA=(SERVICE_NAME={service})))"
    )


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite://"):
        return

    split_result = urlsplit(database_url)
    db_path = split_result.path
    if not db_path or db_path in {"/:memory:", "/:memory"}:
        return

    # sqlite URLs on Windows can start with /C:/..., normalize that for os.path.
    if os.name == "nt" and len(db_path) >= 3 and db_path[0] == "/" and db_path[2] == ":":
        db_path = db_path[1:]

    parent = os.path.dirname(db_path)
    # "/tmp/presenton" becomes the UNC path "//tmp/presenton" on Windows.
    if not parent or parent.startswith(("//", "\\\\")):
        return
    if os.name == "nt" and (parent == "\\tmp\\presenton" or "/tmp/" in db_path):
        return
    os.makedirs(parent, exist_ok=True)


def _int_env(name: str, default: int) -> int:
    """Read an integer from an environment variable, falling back to *default*."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_pool_kwargs() -> dict:
    """Build SQLAlchemy engine pool keyword arguments from environment variables.

    Supported variables (all optional):
        DB_POOL_SIZE          – max persistent connections (default 5)
        DB_MAX_OVERFLOW       – extra connections above pool_size (default 10)
        DB_POOL_TIMEOUT       – seconds to wait for a connection (default 30)
        DB_POOL_RECYCLE       – seconds before a connection is recycled (default 1800)
        DB_POOL_PRE_PING      – enable connection liveness check (default true)

    For SQLite the pool settings are not applicable and an empty dict is
    returned, since SQLite uses ``StaticPool`` / ``NullPool`` by default.
    """
    pool_size = _int_env("DB_POOL_SIZE", 5)
    max_overflow = _int_env("DB_MAX_OVERFLOW", 10)
    if (os.getenv("ORACLE_POOL_MIN") or "").strip():
        pool_size = _int_env("ORACLE_POOL_MIN", pool_size)
    if (os.getenv("ORACLE_POOL_MAX") or "").strip():
        max_overflow = max(0, _int_env("ORACLE_POOL_MAX", pool_size) - pool_size)
    return {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": _int_env("DB_POOL_TIMEOUT", 30),
        "pool_recycle": _int_env("DB_POOL_RECYCLE", 1800),
        "pool_pre_ping": os.getenv("DB_POOL_PRE_PING", "true").lower()
        not in ("false", "0", "no"),
    }


def get_database_url_and_connect_args() -> tuple[str, dict]:
    mode = _persistence_mode()
    explicit = (get_database_url_env() or "").strip()
    # A shared development profile can select Workspace Oracle while explicitly
    # keeping Studio on SQLite. The service-specific URL is authoritative.
    if mode == "oracle" and not explicit:
        dsn = build_oracle_dsn()
        missing = [key for key in ("ORACLE_USER", "ORACLE_PASSWORD") if not os.getenv(key, "").strip()]
        if not dsn:
            missing.append("ORACLE_DSN")
        if missing:
            raise ValueError("Studio Oracle configuration is incomplete: " + ", ".join(missing))
        # Passing the DSN as a driver keyword supports Easy Connect (service
        # names), TNS aliases and full descriptors without unsafe URL assembly.
        url = URL.create(
            "oracle+oracledb_async",
            username=os.environ["ORACLE_USER"],
            password=os.environ["ORACLE_PASSWORD"],
            query={"dsn": dsn},
        )
        return url.render_as_string(hide_password=False), {}
    if not database_is_configured():
        return "sqlite+aiosqlite:///:memory:", {"check_same_thread": False}
    app_data = (get_app_data_directory_env() or "").strip()
    database_url = explicit or ""
    if not database_url:
        if not app_data:
            app_data = str(Path(__file__).resolve().parents[1] / "app_data")
        database_url = "sqlite:///" + os.path.join(app_data, "fastapi.db").replace("\\", "/")
    _ensure_sqlite_parent_dir(database_url)
    url = make_url(database_url)
    drivers = {"sqlite": "sqlite+aiosqlite", "postgresql": "postgresql+asyncpg",
               "postgres": "postgresql+asyncpg", "mysql": "mysql+aiomysql",
               "oracle": "oracle+oracledb_async", "oracle+oracledb": "oracle+oracledb_async"}
    url = url.set(drivername=drivers.get(url.drivername, url.drivername))
    if url.get_backend_name() == "oracle" and url.drivername != "oracle+oracledb_async":
        raise ValueError("Studio Oracle runtime requires the python-oracledb async thin driver")
    connect_args = {"check_same_thread": False} if url.get_backend_name() == "sqlite" else {}
    if url.drivername == "postgresql+asyncpg" and "sslmode" in url.query:
        sslmode = url.query["sslmode"]
        if sslmode != "disable":
            connect_args["ssl"] = ssl.create_default_context()
        url = url.difference_update_query(["sslmode"])
    # Preserve every other query option, notably Oracle service_name/dsn.
    return url.render_as_string(hide_password=False), connect_args


def to_sync_sqlalchemy_url(database_url: str) -> str:
    """Strip async driver prefixes for Alembic and other sync SQLAlchemy engines.

    PostgreSQL URLs use ``postgresql+psycopg://`` (psycopg3) so migrations do not
    depend on psycopg2, which is not installed when using asyncpg at runtime.

    MySQL URLs use ``mysql+pymysql://`` so Alembic does not require ``mysqlclient``
    (the default for plain ``mysql://``); PyMySQL is already pulled in by aiomysql.
    """
    if database_url.startswith("oracle+oracledb_async://"):
        return database_url.replace("oracle+oracledb_async://", "oracle+oracledb://", 1)
    if database_url.startswith("sqlite+aiosqlite:///"):
        return "sqlite:///" + database_url[len("sqlite+aiosqlite:///") :]
    if database_url.startswith("postgresql+asyncpg://"):
        rest = database_url[len("postgresql+asyncpg://") :]
        return f"postgresql+psycopg://{rest}"
    if database_url.startswith("mysql+aiomysql://"):
        rest = database_url[len("mysql+aiomysql://") :]
        return f"mysql+pymysql://{rest}"
    if database_url.startswith("postgresql://"):
        rest = database_url[len("postgresql://") :]
        return f"postgresql+psycopg://{rest}"
    if database_url.startswith("mysql://"):
        rest = database_url[len("mysql://") :]
        return f"mysql+pymysql://{rest}"
    return database_url
