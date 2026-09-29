import os
from utils.get_env import get_app_data_directory_env, get_database_url_env
from urllib.parse import urlsplit
from sqlalchemy.engine import URL, make_url
import ssl


def database_is_configured() -> bool:
    return bool(
        os.getenv("PERSISTENCE_MODE", "").strip().lower() == "oracle"
        or (get_database_url_env() or "").strip()
        or (get_app_data_directory_env() or "").strip()
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
    return {
        "pool_size": _int_env("DB_POOL_SIZE", 5),
        "max_overflow": _int_env("DB_MAX_OVERFLOW", 10),
        "pool_timeout": _int_env("DB_POOL_TIMEOUT", 30),
        "pool_recycle": _int_env("DB_POOL_RECYCLE", 1800),
        "pool_pre_ping": os.getenv("DB_POOL_PRE_PING", "true").lower()
        not in ("false", "0", "no"),
    }


def get_database_url_and_connect_args() -> tuple[str, dict]:
    mode = os.getenv("PERSISTENCE_MODE", "").strip().lower()
    if mode not in {"", "sqlite", "oracle"}:
        raise ValueError("Studio PERSISTENCE_MODE must be sqlite or oracle")
    explicit = (get_database_url_env() or "").strip()
    # A shared development profile can select Workspace Oracle while explicitly
    # keeping Studio on SQLite. The service-specific URL is authoritative.
    if mode == "oracle" and not explicit:
        missing = [key for key in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN") if not os.getenv(key, "").strip()]
        if missing:
            raise ValueError("Studio Oracle configuration is incomplete: " + ", ".join(missing))
        # Passing the DSN as a driver keyword supports Easy Connect (service
        # names), TNS aliases and full descriptors without unsafe URL assembly.
        url = URL.create("oracle+oracledb_async", username=os.environ["ORACLE_USER"],
                         password=os.environ["ORACLE_PASSWORD"], query={"dsn": os.environ["ORACLE_DSN"]})
        return url.render_as_string(hide_password=False), {}
    if not database_is_configured():
        return "sqlite+aiosqlite:///:memory:", {"check_same_thread": False}
    app_data = (get_app_data_directory_env() or "").strip()
    database_url = explicit or "sqlite:///" + os.path.join(app_data, "fastapi.db").replace("\\", "/")
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
