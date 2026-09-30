import asyncio
import inspect
import threading
import warnings

from sqlalchemy.engine import URL

from utils.oracle_thick import _ThickConnection, _ThickCursor, credentials_from_sqlalchemy_url


class _FakeCursor:
    def __init__(self):
        self.arraysize = 0
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((threading.get_ident(), sql, params))
        return sql

    def setinputsizes(self, *args, **kwargs):
        self.calls.append((threading.get_ident(), "setinputsizes", kwargs or args))
        return kwargs or args

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


def test_sqlalchemy_setinputsizes_runs_instead_of_returning_a_coroutine():
    from sqlalchemy.dialects.oracle.cx_oracle import OracleDialect_cx_oracle

    wrapper = _ThickConnection()
    raw = _FakeConnection()
    object.__setattr__(wrapper, "_conn", raw)
    cursor = wrapper.cursor()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            OracleDialect_cx_oracle().do_set_input_sizes(
                cursor,
                [("content", str, None), ("skipped", None, None)],
                None,
            )
        assert not any("never awaited" in str(item.message) for item in caught)
        inner = cursor._cursor
        assert (inner.calls[0][1], inner.calls[0][2]) == ("setinputsizes", {"content": str})
        assert inner.calls[0][0] == raw.cursor_thread
    finally:
        cursor.close()
        wrapper._executor.shutdown(wait=True)


def test_thick_cursor_runs_on_one_connection_thread():
    wrapper = _ThickConnection()
    raw = _FakeConnection()
    object.__setattr__(wrapper, "_conn", raw)

    async def _use():
        cursor = wrapper.cursor()
        cursor.arraysize = 50
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            bound = cursor.setinputsizes(content=str)
        await cursor.execute("SELECT 1 FROM DUAL")
        rows = await cursor.fetchall()
        await wrapper.commit()
        inner = cursor._cursor
        cursor.close()
        return inner, rows, bound, caught

    inner, rows, bound, caught = asyncio.run(_use())
    assert rows == [("ok",)]
    assert bound == {"content": str}
    assert not inspect.iscoroutine(bound)
    assert not inspect.iscoroutinefunction(_ThickCursor.setinputsizes)
    assert not any("never awaited" in str(item.message) for item in caught)
    assert inner.arraysize == 50
    worker = raw.cursor_thread
    sizes = next(call for call in inner.calls if call[1] == "setinputsizes")
    assert sizes[0] == worker
    assert inner.calls[-1][0] == worker
    assert any(call[1] == "SELECT 1 FROM DUAL" for call in inner.calls)
    wrapper._executor.shutdown(wait=True)
