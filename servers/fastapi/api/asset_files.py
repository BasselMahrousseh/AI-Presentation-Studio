"""Serve authorized Studio objects through the existing /app_data contract."""

import asyncio
import os
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse

from services.asset_storage import (
    AssetAccessDenied, AssetNotFound, AssetStorageError, get_asset_storage,
)


class StoredAssetFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if scope["method"] not in {"GET", "HEAD"}:
            raise HTTPException(405)
        try:
            local = await asyncio.to_thread(
                get_asset_storage().materialize, "/app_data/" + path.replace(os.sep, "/")
            )
        except (AssetAccessDenied, AssetNotFound):
            raise HTTPException(404, "Asset not found")
        except AssetStorageError:
            raise HTTPException(503, "Studio object storage unavailable")
        return FileResponse(local, headers={
            "Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff",
        })
