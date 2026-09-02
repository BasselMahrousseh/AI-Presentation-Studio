import json
import logging
import os
import tempfile
import time
from typing import Any, Optional

from utils.get_env import get_temp_directory_env

LOGGER = logging.getLogger(__name__)

_CAPTURE_SUBDIR = "chart_capture"
_STALE_MAX_AGE_SECONDS = 3600


def _capture_directory() -> str:
    root = get_temp_directory_env() or os.path.join(tempfile.gettempdir(), "presenton")
    directory = os.path.join(root, _CAPTURE_SUBDIR)
    os.makedirs(directory, exist_ok=True)
    return directory


def _capture_path(token: str) -> str:
    # Token is normally a server-minted uuid4, but it round-trips through an
    # unauthenticated-by-design best-effort endpoint, so sanitize before it
    # becomes part of a filesystem path.
    safe_token = "".join(ch for ch in token if ch.isalnum() or ch in "-_")
    if not safe_token:
        raise ValueError("empty chart capture token")
    return os.path.join(_capture_directory(), f"{safe_token}.json")


def write_capture(token: str, presentation_id: str, charts: list[dict]) -> None:
    """Best-effort. Logs and returns on any failure rather than raising."""
    try:
        path = _capture_path(token)
    except ValueError:
        LOGGER.warning("chart_capture_store: refusing to write capture for empty token")
        return

    payload = {"presentation_id": presentation_id, "charts": charts}
    tmp_path = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp_path, path)
    except Exception:
        LOGGER.exception(
            "chart_capture_store: failed to write capture for token=%s", token
        )
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def take_capture(token: str) -> Optional[dict[str, Any]]:
    """Read-then-delete. Returns None if absent or unreadable; never raises."""
    try:
        path = _capture_path(token)
    except ValueError:
        return None

    data: Optional[dict[str, Any]] = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except Exception:
        LOGGER.exception(
            "chart_capture_store: failed to read capture for token=%s", token
        )
        data = None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return data


def sweep_stale_captures(max_age_seconds: int = _STALE_MAX_AGE_SECONDS) -> None:
    """Deletes leftover capture files (e.g. from a crashed export) on startup."""
    try:
        directory = _capture_directory()
        now = time.time()
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            try:
                if now - os.path.getmtime(path) > max_age_seconds:
                    os.remove(path)
            except OSError:
                continue
    except Exception:
        LOGGER.exception("chart_capture_store: failed to sweep stale captures")
