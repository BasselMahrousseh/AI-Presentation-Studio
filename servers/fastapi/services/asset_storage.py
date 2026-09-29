"""Durable Studio assets with private S3 objects and owner-checked local staging.

Database/browser references use /app_data paths, never machine paths or public
bucket URLs. Call blocking methods with asyncio.to_thread from request handlers.
"""

import base64
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import mimetypes
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import quote
import uuid

from api.v1.auth.assets import (
    PRIVATE_APP_DATA_ROOTS, SHARED_APP_DATA_ROOTS, is_app_data_path_authorized,
    normalized_app_data_parts,
)
from api.v1.auth.context import get_current_owner_id, get_current_owner_is_admin
from utils.get_env import is_disable_auth_enabled, get_app_data_directory_env, get_temp_directory_env


class AssetStorageError(RuntimeError):
    """A storage operation failed; messages never include provider credentials."""


class AssetNotFound(AssetStorageError):
    pass


class AssetAccessDenied(AssetStorageError):
    pass


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    if value.lower() not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} must be a boolean")
    return value.lower() in {"true", "1", "yes"}


def _integer(name: str, default: int, maximum: int) -> int:
    value = int(os.getenv(name) or default)
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


@dataclass(frozen=True)
class AssetStorageConfig:
    root: str
    backend: str = "filesystem"
    bucket: str = ""
    prefix: str = "genai-artifacts"
    region: str = ""
    endpoint: str = ""
    access_key: str = field(default="", repr=False)
    secret_key: str = field(default="", repr=False)
    session_token: str = field(default="", repr=False)
    kms_key: str = field(default="", repr=False)
    verify_ssl: bool = True
    ca_bundle: str = ""
    addressing_style: str = "auto"
    connect_timeout: int = 10
    read_timeout: int = 60
    max_attempts: int = 3

    @classmethod
    def from_environment(cls):
        backend = (os.getenv("ARTIFACT_STORAGE_BACKEND") or "filesystem").strip().lower()
        if backend == "s3" and not _boolean("ARTIFACT_S3_ENABLED", True):
            raise ValueError("ARTIFACT_STORAGE_BACKEND=s3 conflicts with ARTIFACT_S3_ENABLED=false")
        if backend not in {"filesystem", "s3"}:
            raise ValueError("Studio ARTIFACT_STORAGE_BACKEND must be filesystem or s3")
        root = (os.getenv("APP_DATA_DIRECTORY") or "").strip()
        if backend == "s3" and not root:
            raise ValueError("APP_DATA_DIRECTORY is required for Studio S3 staging")
        config = cls(
            root=get_app_data_directory_env(),
            backend=backend,
            bucket=(os.getenv("ARTIFACT_S3_BUCKET") or "").strip(),
            prefix=(os.getenv("ARTIFACT_S3_PREFIX") or "genai-artifacts").strip("/"),
            region=(os.getenv("ARTIFACT_S3_REGION") or "").strip(),
            endpoint=(os.getenv("ARTIFACT_S3_ENDPOINT_URL") or "").strip(),
            access_key=os.getenv("ARTIFACT_S3_ACCESS_KEY_ID") or "",
            secret_key=os.getenv("ARTIFACT_S3_SECRET_ACCESS_KEY") or "",
            session_token=os.getenv("ARTIFACT_S3_SESSION_TOKEN") or "",
            kms_key=os.getenv("ARTIFACT_S3_KMS_KEY_ID") or "",
            verify_ssl=_boolean("ARTIFACT_S3_VERIFY_SSL", True),
            ca_bundle=(os.getenv("ARTIFACT_S3_CA_BUNDLE") or "").strip(),
            addressing_style=os.getenv("ARTIFACT_S3_ADDRESSING_STYLE") or "auto",
            connect_timeout=_integer("ARTIFACT_S3_CONNECT_TIMEOUT_SECONDS", 10, 120),
            read_timeout=_integer("ARTIFACT_S3_READ_TIMEOUT_SECONDS", 60, 600),
            max_attempts=_integer("ARTIFACT_S3_MAX_ATTEMPTS", 3, 10),
        )
        if backend == "s3" and not config.bucket:
            raise ValueError("ARTIFACT_S3_BUCKET is required for Studio S3 storage")
        temp_root = Path(get_temp_directory_env() or Path(tempfile.gettempdir()) / "presenton").resolve()
        if Path(config.root).expanduser().resolve().is_relative_to(temp_root):
            raise ValueError("APP_DATA_DIRECTORY must be outside TEMP_DIRECTORY")
        if config.ca_bundle and (not config.verify_ssl or not Path(config.ca_bundle).is_file()):
            raise ValueError("ARTIFACT_S3_CA_BUNDLE requires an existing PEM file and ARTIFACT_S3_VERIFY_SSL=true")
        if bool(config.access_key) != bool(config.secret_key):
            raise ValueError("Studio S3 access key and secret key must be configured together")
        if config.addressing_style not in {"auto", "virtual", "path"}:
            raise ValueError("Invalid ARTIFACT_S3_ADDRESSING_STYLE")
        if any(part in {"", ".", ".."} for part in config.prefix.split("/")) or "\\" in config.prefix:
            raise ValueError("ARTIFACT_S3_PREFIX must be a relative object prefix")
        return config


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class AssetStorage:
    def __init__(self, config: AssetStorageConfig, *, client=None):
        self.config = config
        self.root = Path(config.root).expanduser().resolve()
        self._client = client

    @property
    def is_s3(self) -> bool:
        return self.config.backend == "s3"

    def _s3(self):
        if self._client is None:
            import boto3
            from botocore.config import Config
            kwargs = {
                "region_name": self.config.region, "endpoint_url": self.config.endpoint,
                "aws_access_key_id": self.config.access_key,
                "aws_secret_access_key": self.config.secret_key,
                "aws_session_token": self.config.session_token,
            }
            self._client = boto3.client(
                "s3", **{key: value for key, value in kwargs.items() if value},
                verify=self.config.ca_bundle or (None if self.config.verify_ssl else False),
                config=Config(
                    connect_timeout=self.config.connect_timeout,
                    read_timeout=self.config.read_timeout,
                    retries={"max_attempts": self.config.max_attempts, "mode": "standard"},
                    s3={"addressing_style": self.config.addressing_style},
                ),
            )
        return self._client

    def parts(self, reference: str) -> tuple[str, ...]:
        # Canonical references have no authority, fragment, or query component.
        if not isinstance(reference, str) or not reference.startswith("/app_data/") or any(c in reference for c in "?#"):
            raise AssetAccessDenied("Invalid Studio asset reference")
        parts = normalized_app_data_parts(reference)
        if not parts or parts[0] not in PRIVATE_APP_DATA_ROOTS | SHARED_APP_DATA_ROOTS:
            raise AssetAccessDenied("Invalid Studio asset reference")
        return parts

    def authorize(self, reference: str) -> tuple[str, ...]:
        parts = self.parts(reference)
        if parts[0] in SHARED_APP_DATA_ROOTS:
            return parts
        owner = get_current_owner_id()
        if self.is_s3:
            if owner is not None and len(parts) >= 4 and parts[1:3] == ("users", str(owner)):
                return parts
            raise AssetAccessDenied("Studio asset not found")
        if owner is not None and is_app_data_path_authorized(
            reference, user_id=owner, is_admin=get_current_owner_is_admin()
        ):
            return parts
        if not self.is_s3 and owner is None and is_disable_auth_enabled():
            return parts
        raise AssetAccessDenied("Studio asset not found")

    def object_key(self, reference: str) -> str:
        return "/".join((self.config.prefix, "studio", *self.parts(reference)))

    def local_path(self, reference: str) -> Path:
        parts = self.parts(reference)
        path = self.root.joinpath(*parts)
        # Reject symlinks even if they currently point inside the root: they can
        # change between validation and a write or point at another owner's cache.
        cursor = path
        while cursor != self.root and cursor != cursor.parent:
            if cursor.is_symlink():
                raise AssetAccessDenied("Invalid Studio asset cache path")
            cursor = cursor.parent
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise AssetAccessDenied("Invalid Studio asset cache path")
        return resolved

    def reference_for_path(self, path: str | Path) -> str:
        if isinstance(path, str) and path.startswith("/app_data/"):
            self.parts(path)
            return path
        raw = Path(path).expanduser().resolve()
        try:
            relative = raw.relative_to(self.root)
        except ValueError as exc:
            raise AssetAccessDenied("File is outside Studio application storage") from exc
        reference = "/app_data/" + quote(relative.as_posix(), safe="/")
        self.local_path(reference)
        return reference

    def new_reference(self, kind: str, filename: str) -> str:
        if kind not in PRIVATE_APP_DATA_ROOTS:
            raise AssetAccessDenied("Invalid Studio asset kind")
        filename = Path(filename.replace("\\", "/")).name.strip()
        if filename in {"", ".", ".."} or any(c in filename for c in "\x00?#"):
            raise AssetAccessDenied("Invalid Studio asset filename")
        owner = get_current_owner_id()
        if owner is None:
            if self.is_s3 or not is_disable_auth_enabled():
                raise AssetAccessDenied("An owner is required for Studio assets")
            parts = (kind, str(uuid.uuid4()), filename)
        else:
            parts = (kind, "users", str(owner), str(uuid.uuid4()), filename)
        return "/app_data/" + quote("/".join(parts), safe="/")

    @staticmethod
    def _translate(exc: Exception):
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise AssetNotFound("Studio asset not found") from exc
        raise AssetStorageError("Studio object storage operation failed") from exc

    def _head(self, reference: str):
        try:
            return self._s3().head_object(Bucket=self.config.bucket, Key=self.object_key(reference))
        except Exception as exc:
            self._translate(exc)

    def publish(self, source: str | Path, reference: str, *, migration: bool = False) -> str:
        """Publish bytes before returning their durable reference.

        migration=True is only for the explicit offline migration CLI, after its
        full owner/reference preflight; request handlers must never supply it.
        """
        if migration:
            self.parts(reference)
        else:
            self.authorize(reference)
        source = Path(source).resolve()
        if not source.is_file():
            raise AssetNotFound("Studio source file not found")
        destination = self.local_path(reference)
        checksum = file_sha256(source)
        if self.is_s3:
            params = {
                "Bucket": self.config.bucket, "Key": self.object_key(reference),
                "ContentType": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
                "ContentLength": source.stat().st_size,
                "Metadata": {"sha256": checksum}, "ChecksumAlgorithm": "SHA256",
                "ChecksumSHA256": base64.b64encode(bytes.fromhex(checksum)).decode("ascii"),
                "ServerSideEncryption": "aws:kms" if self.config.kms_key else "AES256",
            }
            if self.config.kms_key:
                params["SSEKMSKeyId"] = self.config.kms_key
            try:
                # Existing names are immutable unless the bytes are identical;
                # this also makes interrupted migration runs safe to repeat.
                try:
                    existing = self._head(reference)
                except AssetNotFound:
                    existing = None
                if existing:
                    if existing.get("Metadata", {}).get("sha256") != checksum or existing.get("ContentLength") != source.stat().st_size:
                        raise AssetStorageError("Studio object already exists with different content")
                else:
                    with source.open("rb") as handle:
                        self._s3().put_object(Body=handle, IfNoneMatch="*", **params)
                verified = self._head(reference)
                if verified.get("Metadata", {}).get("sha256") != checksum or verified.get("ContentLength") != source.stat().st_size:
                    raise AssetStorageError("Studio object verification failed")
            except AssetStorageError:
                raise
            except Exception as exc:
                self._translate(exc)
        if source != destination:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
            try:
                shutil.copyfile(source, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        return reference

    def publish_new(self, source: str | Path, kind: str) -> str:
        return self.publish(source, self.new_reference(kind, Path(source).name))

    def publish_existing(self, source: str | Path) -> str:
        return self.publish(source, self.reference_for_path(source))

    def materialize(self, reference: str) -> str:
        # Check ownership before looking at the cache or touching S3.
        self.authorize(reference)
        destination = self.local_path(reference)
        if not self.is_s3:
            if not destination.is_file():
                raise AssetNotFound("Studio asset not found")
            return str(destination)
        metadata = self._head(reference)  # S3 is authoritative even on a cache hit.
        checksum = metadata.get("Metadata", {}).get("sha256")
        if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
            raise AssetStorageError("Studio object is missing verified checksum metadata")
        if destination.is_file() and destination.stat().st_size == metadata.get("ContentLength") and checksum and file_sha256(destination) == checksum:
            return str(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".part")
        try:
            response = self._s3().get_object(Bucket=self.config.bucket, Key=self.object_key(reference))
            body = response["Body"]
            try:
                with temporary.open("wb") as handle:
                    shutil.copyfileobj(body, handle, 1024 * 1024)
            finally:
                body.close()
            if temporary.stat().st_size != metadata.get("ContentLength") or (checksum and file_sha256(temporary) != checksum):
                raise AssetStorageError("Studio object integrity check failed")
            os.replace(temporary, destination)
        except AssetStorageError:
            raise
        except Exception as exc:
            self._translate(exc)
        finally:
            temporary.unlink(missing_ok=True)
        return str(destination)

    def delete(self, reference: str) -> None:
        self.authorize(reference)
        destination = self.local_path(reference)
        if self.is_s3:
            try:
                self._s3().delete_object(Bucket=self.config.bucket, Key=self.object_key(reference))
            except Exception as exc:
                self._translate(exc)
        destination.unlink(missing_ok=True)


@lru_cache(maxsize=4)
def _configured_storage(config: AssetStorageConfig) -> AssetStorage:
    return AssetStorage(config)


def get_asset_storage() -> AssetStorage:
    return _configured_storage(AssetStorageConfig.from_environment())
