"""Oracle thick-mode connections for listeners that require Native Network Encryption.

python-oracledb asyncio is thin-only and raises DPY-3001 against this listener.
Each thick connection is used from one dedicated thread; the async SQLAlchemy
session API stays unchanged.
"""

import asyncio
import logging
import os
import platform
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

_init_lock = threading.Lock()
_thick_ready = False


def _configured_client_dir() -> str | None:
    configured = (os.getenv("ORACLE_CLIENT_PATH") or "").strip()
    if configured:
        return configured
    if platform.system() != "Windows":
        return None
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if folder and os.path.isfile(os.path.join(folder, "oci.dll")):
            return None
    candidates = [
        os.path.expanduser(r"~\Downloads\instantclient_23_5"),
        r"C:\oracle\instantclient_23_5",
        r"C:\instantclient_23_5",
    ]
    for path in candidates:
        if os.path.isfile(os.path.join(path, "oci.dll")):
            return path
    return None


def ensure_oracle_thick_mode() -> None:
    """Load Instant Client once. Required before any connection on this listener."""
    global _thick_ready
    with _init_lock:
        if _thick_ready:
            return
        import oracledb

        if not oracledb.is_thin_mode():
            _thick_ready = True
            return
        lib_dir = _configured_client_dir()
        try:
            if lib_dir:
                oracledb.init_oracle_client(lib_dir=lib_dir)
            else:
                oracledb.init_oracle_client()
        except Exception as exc:
            raise RuntimeError(
                "This Oracle listener requires Native Network Encryption (thick mode). "
                "Install Oracle Instant Client and set ORACLE_CLIENT_PATH to the folder "
                "that contains oci.dll."
            ) from exc
        _thick_ready = True
        logger.info("Oracle thick mode enabled (Instant Client%s)", f": {lib_dir}" if lib_dir else "")


def credentials_from_sqlalchemy_url(database_url: str) -> tuple[str, str, str]:
    url = make_url(database_url)
    dsn = url.query.get("dsn")
    if not dsn and url.host:
        port = url.port or 1521
        service = url.query.get("service_name")
        if service:
            dsn = (
                f"(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST={url.host})(PORT={port}))"
                f"(CONNECT_DATA=(SERVICE_NAME={service})))"
            )
        elif url.database:
            dsn = f"{url.host}:{port}/{url.database}"
    if not url.username or not dsn:
        raise RuntimeError("Oracle username or DSN is missing")
    return url.username, url.password or "", str(dsn)


class _ThickCursor:
    """Sync Oracle cursor exposed as the async cursor SQLAlchemy awaits."""

    def __init__(self, cursor, executor: ThreadPoolExecutor):
        self._cursor = cursor
        self._executor = executor

    def _call(self, fn, *args, **kwargs):
        return self._executor.submit(lambda: fn(*args, **kwargs)).result()

    async def _acall(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    async def execute(self, operation, parameters=None):
        if parameters is None:
            return await self._acall(self._cursor.execute, operation)
        return await self._acall(self._cursor.execute, operation, parameters)

    async def executemany(self, operation, parameters):
        return await self._acall(self._cursor.executemany, operation, parameters)

    async def fetchall(self):
        return await self._acall(self._cursor.fetchall)

    async def fetchone(self):
        return await self._acall(self._cursor.fetchone)

    async def fetchmany(self, size=None):
        if size is None:
            return await self._acall(self._cursor.fetchmany)
        return await self._acall(self._cursor.fetchmany, size)

    def setinputsizes(self, *args, **kwargs):
        # python-oracledb's AsyncCursor.setinputsizes is synchronous, and
        # SQLAlchemy's async Oracle adapter calls it without awaiting.
        return self._call(self._cursor.setinputsizes, *args, **kwargs)

    def nextset(self):
        # SQLAlchemy's generic adapter awaits this; the real AsyncCursor method
        # is synchronous. Returning a coroutine keeps that await working.
        return self._acall(self._cursor.nextset)

    def var(self, *args, **kwargs):
        return self._call(self._cursor.var, *args, **kwargs)

    @property
    def arraysize(self):
        return self._call(lambda: self._cursor.arraysize)

    @arraysize.setter
    def arraysize(self, value):
        self._call(setattr, self._cursor, "arraysize", value)

    @property
    def description(self):
        return self._call(lambda: self._cursor.description)

    @property
    def rowcount(self):
        return self._call(lambda: self._cursor.rowcount)

    @property
    def outputtypehandler(self):
        return self._call(lambda: self._cursor.outputtypehandler)

    @outputtypehandler.setter
    def outputtypehandler(self, value):
        self._call(setattr, self._cursor, "outputtypehandler", value)

    def close(self):
        if self._cursor is not None:
            self._call(self._cursor.close)
            self._cursor = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def __getattr__(self, name):
        value = self._call(getattr, self._cursor, name)
        if not callable(value):
            return value

        def _method(*args, **kwargs):
            return self._call(getattr(self._cursor, name), *args, **kwargs)

        return _method


class _ThickConnection:
    def __init__(self):
        object.__setattr__(
            self,
            "_executor",
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="oracle-thick"),
        )
        object.__setattr__(self, "_conn", None)

    def __setattr__(self, name, value):
        if name in {"_executor", "_conn"}:
            object.__setattr__(self, name, value)
            return
        self._call(setattr, self._conn, name, value)

    def _call(self, fn, *args, **kwargs):
        return self._executor.submit(lambda: fn(*args, **kwargs)).result()

    async def _acall(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    def connect(self, user: str, password: str, dsn: str) -> None:
        import oracledb

        def _open():
            # Assign directly. __setattr__ would submit back onto this same thread.
            object.__setattr__(
                self,
                "_conn",
                oracledb.connect(user=user, password=password, dsn=dsn),
            )

        try:
            self._executor.submit(_open).result()
        except Exception:
            self._executor.shutdown(wait=False, cancel_futures=True)
            raise

    def cursor(self):
        raw = self._call(self._conn.cursor)
        return _ThickCursor(raw, self._executor)

    async def commit(self):
        await self._acall(self._conn.commit)

    async def rollback(self):
        await self._acall(self._conn.rollback)

    async def close(self):
        try:
            if self._conn is not None:
                await self._acall(self._conn.close)
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)

    async def tpc_begin(self, *args, **kwargs):
        return await self._acall(self._conn.tpc_begin, *args, **kwargs)

    async def tpc_commit(self, *args, **kwargs):
        return await self._acall(self._conn.tpc_commit, *args, **kwargs)

    async def tpc_prepare(self, *args, **kwargs):
        return await self._acall(self._conn.tpc_prepare, *args, **kwargs)

    async def tpc_recover(self, *args, **kwargs):
        return await self._acall(self._conn.tpc_recover, *args, **kwargs)

    async def tpc_rollback(self, *args, **kwargs):
        return await self._acall(self._conn.tpc_rollback, *args, **kwargs)

    def __getattr__(self, name):
        value = self._call(getattr, self._conn, name)
        if not callable(value):
            return value

        def _method(*args, **kwargs):
            return self._call(getattr(self._conn, name), *args, **kwargs)

        return _method


async def open_thick_connection(database_url: str) -> _ThickConnection:
    ensure_oracle_thick_mode()
    user, password, dsn = credentials_from_sqlalchemy_url(database_url)
    connection = _ThickConnection()
    logger.info("Connecting to Oracle as %s", user)
    await asyncio.to_thread(connection.connect, user, password, dsn)
    logger.info("Oracle session open")
    return connection
