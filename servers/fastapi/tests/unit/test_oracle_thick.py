import asyncio
import threading

from sqlalchemy.engine import URL

from utils.oracle_thick import _ThickConnection, credentials_from_sqlalchemy_url


class _FakeCursor:
    def __init__(self):
        self.arraysize = 0
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((threading.get_ident(), sql, params))
        return sql

    def fetchall(self):
        return [("ok",)]

    def close(self):
        self.calls.append((threading.get_ident(), "close", None))


class _FakeConnection:
    def __init__(self):
        self.cursor_thread = None

    def cursor(self):
        self.cursor_thread = threading.get_ident()
        return _FakeCursor()

    def commit(self):
        return "committed"


def test_sqlalchemy_url_keeps_password_and_dsn():
    url = URL.create(
        "oracle+oracledb_async",
        username="aidev",
        password="AiDev$12$45",
        query={"dsn": "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.1.1.1)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=FREEPDB1)))"},
    ).render_as_string(hide_password=False)
    user, password, dsn = credentials_from_sqlalchemy_url(url)
    assert user == "aidev"
    assert password == "AiDev$12$45"
    assert "HOST=10.1.1.1" in dsn
    assert "SERVICE_NAME=FREEPDB1" in dsn


def test_thick_cursor_runs_on_one_connection_thread():
    wrapper = _ThickConnection()
    raw = _FakeConnection()
    object.__setattr__(wrapper, "_conn", raw)

    async def _use():
        cursor = wrapper.cursor()
        cursor.arraysize = 50
        await cursor.execute("SELECT 1 FROM DUAL")
        rows = await cursor.fetchall()
        await wrapper.commit()
        inner = cursor._cursor
        cursor.close()
        return inner, rows

    inner, rows = asyncio.run(_use())
    assert rows == [("ok",)]
    assert inner.arraysize == 50
    worker = raw.cursor_thread
    assert inner.calls[0][0] == worker
    assert inner.calls[0][1] == "SELECT 1 FROM DUAL"
    wrapper._executor.shutdown(wait=True)
