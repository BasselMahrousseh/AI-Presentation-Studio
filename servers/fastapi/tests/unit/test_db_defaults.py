from pathlib import Path

from utils.db_utils import get_database_url_and_connect_args


def test_unconfigured_database_uses_local_sqlite_file(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_DATA_DIRECTORY", raising=False)

    url, connect_args = get_database_url_and_connect_args()

    expected = Path(__file__).resolve().parents[2] / "app_data" / "fastapi.db"
    assert url == "sqlite+aiosqlite:///" + str(expected).replace("\\", "/")
    assert connect_args["check_same_thread"] is False
    assert expected.parent.is_dir()


def test_app_data_directory_uses_sqlite_file(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path))

    url, _connect_args = get_database_url_and_connect_args()

    assert url.endswith("/fastapi.db")
    assert ":memory:" not in url
