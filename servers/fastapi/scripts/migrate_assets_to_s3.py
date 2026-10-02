"""Copy Studio assets to S3 and rewrite source SQLite references explicitly.

Dry run is the default and never contacts S3. Stop writers and back up the source
database/files before --apply. Source files are never moved or deleted.
"""

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, unquote, urlsplit
import uuid

from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, select, update
from sqlalchemy.orm import Session

from api.v1.auth.assets import PRIVATE_APP_DATA_ROOTS, SHARED_APP_DATA_ROOTS, normalized_app_data_parts
from models.sql.user import User
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.sql.image_asset import ImageAsset
from models.sql.chat_history_message import ChatHistoryMessageModel  # registers FK metadata
from models.sql.generation_feedback import GenerationFeedback  # registers FK metadata
from services.asset_migration import owner_string, transform_record_references
from services.asset_storage import AssetStorage, AssetStorageConfig, file_sha256
from utils.schema_names import canonical_schema_tables


@dataclass
class CopyItem:
    source: str
    reference: str
    sha256: str
    bytes: int


class AssetPlan:
    def __init__(self, app_data_root, upload_root, owners, legacy_origins=(), cache_root=None):
        self.app_root = Path(app_data_root).resolve()
        self.upload_root = Path(upload_root).resolve() if upload_root else None
        self.cache_root = Path(cache_root).resolve() if cache_root else None
        self.owners = set(owners)
        self.legacy_origins = {origin.rstrip("/") for origin in legacy_origins}
        self.items: dict[str, CopyItem] = {}
        self.sources: dict[str, tuple[str, str | None]] = {}
        self.issues: list[str] = []
        self.warnings: list[str] = []

    def _add(self, source: Path, reference: str, owner) -> str:
        if source.is_symlink() or any(parent.is_symlink() for parent in source.parents):
            raise ValueError("Symlinked assets require explicit operator review")
        source = source.resolve()
        if not source.is_file():
            raise ValueError("Referenced source file is missing")
        if not source.is_relative_to(self.app_root) and not (
            self.upload_root and source.is_relative_to(self.upload_root)
        ) and not (self.cache_root and source.is_relative_to(self.cache_root)):
            raise ValueError("Source file is outside the explicitly selected roots")
        source_key = str(source)
        old = self.sources.get(source_key)
        if old and old != (reference, owner):
            raise ValueError("One source file has conflicting ownership or destinations")
        item = CopyItem(source_key, reference, file_sha256(source), source.stat().st_size)
        existing = self.items.get(reference)
        if existing and (existing.sha256, existing.bytes) != (item.sha256, item.bytes):
            raise ValueError("Different files map to the same S3 object")
        self.items.setdefault(reference, item)
        self.sources[source_key] = (reference, owner)
        return reference

    def _from_app_path(self, source: Path, owner, required_kind, *, canonical=False):
        relative = source.relative_to(self.app_root)
        parts = relative.parts
        if not parts or parts[0] not in PRIVATE_APP_DATA_ROOTS | SHARED_APP_DATA_ROOTS:
            raise ValueError("Unsupported application asset directory")
        if required_kind and parts[0] != required_kind:
            raise ValueError("Source file has the wrong asset kind")
        # A completed run may have rewritten references while staging in a
        # different directory. Reuse only that exact canonical destination,
        # never a guessed legacy basename or a different owner's cached file.
        if canonical and not source.exists() and self.cache_root:
            candidate = self.cache_root.joinpath(*parts)
            if candidate.is_file():
                source = candidate
        if parts[0] in SHARED_APP_DATA_ROOTS:
            if required_kind:
                raise ValueError("Private source reference cannot use shared assets")
            return self._add(source, "/app_data/" + quote(relative.as_posix(), safe="/"), None)
        if owner not in self.owners:
            raise ValueError("Asset requires a mapped Workspace owner; run owner backfill first")
        if len(parts) >= 2 and parts[1] == "users":
            if len(parts) < 4 or parts[2] != owner:
                raise ValueError("Source directory does not match the database owner")
            target = relative.as_posix()
        else:
            target = "/".join((parts[0], "users", owner, *parts[1:]))
        return self._add(source, "/app_data/" + quote(target, safe="/"), owner)

    def transform(self, value, owner, field, required_kind):
        if not isinstance(value, str) or not value:
            if required_kind:
                raise ValueError("Required file reference is missing")
            return value
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"}:
            if not parsed.path.startswith("/app_data/"):
                return value if not required_kind else self._unsupported()
            if f"{parsed.scheme}://{parsed.netloc}" not in self.legacy_origins:
                raise ValueError("Absolute Studio URL requires its explicit --legacy-origin")
            value = parsed.path
        if value.startswith("/app_data/"):
            parts = normalized_app_data_parts(value)
            if not parts or any(char in value for char in "?#"):
                raise ValueError("Invalid application asset reference")
            return self._from_app_path(self.app_root.joinpath(*parts), owner, required_kind, canonical=True)
        if value.startswith(("/static/", "data:", "blob:", "//")):
            return value if not required_kind else self._unsupported()
        if parsed.scheme == "file":
            if parsed.netloc:
                raise ValueError("Remote file URLs are unsupported")
            value = unquote(parsed.path)
            if os.name == "nt" and re.match(r"^/[A-Za-z]:/", value):
                value = value[1:]
        local = Path(value)
        if not local.is_absolute():
            if required_kind or re.match(r"^[A-Za-z]:[\\/]", value):
                raise ValueError("Source path must be available under an explicit local root")
            return value
        # Do not follow a symlink before checking that the selected source is safe.
        if local.is_symlink() or any(parent.is_symlink() for parent in local.parents if parent != self.app_root):
            raise ValueError("Symlinked source paths require explicit operator review")
        local = local.resolve()
        if local.is_relative_to(self.app_root):
            return self._from_app_path(local, owner, required_kind)
        if self.upload_root and local.is_relative_to(self.upload_root):
            if owner not in self.owners or required_kind not in {None, "uploads"}:
                raise ValueError("Legacy upload has no compatible Workspace owner")
            parts = local.relative_to(self.upload_root).parts
            if parts and parts[0] in self.owners:
                if parts[0] != owner:
                    raise ValueError("Legacy upload belongs to a different owner")
                parts = parts[1:]
            reference = "/app_data/" + quote("/".join(("uploads", "users", owner, *parts)), safe="/")
            return self._add(local, reference, owner)
        raise ValueError("Local asset is outside the selected roots")

    @staticmethod
    def _unsupported():
        raise ValueError("Durable private references must point to local source assets")

    def scan_unreferenced(self):
        # Export files have no ORM row. Copy owned ones without inventing owners.
        for kind in sorted(PRIVATE_APP_DATA_ROOTS | SHARED_APP_DATA_ROOTS):
            base = self.app_root / kind
            if not base.is_dir():
                continue
            for source in sorted(base.rglob("*")):
                if not source.is_file() or str(source.resolve()) in self.sources:
                    continue
                relative = source.relative_to(self.app_root).parts
                owner = relative[2] if len(relative) >= 4 and relative[1] == "users" else None
                try:
                    self._from_app_path(source, owner, None)
                except ValueError as exc:
                    self.warnings.append(f"Unreferenced file left unchanged: {source}: {exc}")


def _read_configuration(path: Path) -> AssetStorageConfig:
    seen = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match:
            if match[1] in seen:
                raise ValueError(f"Duplicate configuration key {match[1]} at line {line_no}")
            seen.add(match[1])
    values = {key: value for key, value in dotenv_values(path, interpolate=False).items() if value is not None}
    previous = os.environ.copy()
    try:
        # The selected file is authoritative for storage; unrelated shell values
        # must not choose a different bucket or credential pair.
        for key in list(os.environ):
            if key.startswith("ARTIFACT_") or key in {"APP_DATA_DIRECTORY", "TEMP_DIRECTORY"}:
                os.environ.pop(key)
        os.environ.update({key: value for key, value in values.items() if key.startswith("ARTIFACT_") or key in {"APP_DATA_DIRECTORY", "TEMP_DIRECTORY"}})
        config = AssetStorageConfig.from_environment()
    finally:
        os.environ.clear()
        os.environ.update(previous)
    if config.backend != "s3":
        raise ValueError("The selected environment must enable S3 storage")
    return config


def migrate(source_sqlite: Path, app_data_root: Path, storage: AssetStorage, *,
            legacy_upload_root: Path | None = None, legacy_origins=(), apply=False) -> dict:
    source_sqlite = Path(source_sqlite).resolve()
    app_data_root = Path(app_data_root).resolve()
    if not source_sqlite.is_file() or not app_data_root.is_dir():
        raise ValueError("An existing source SQLite database and app-data directory are required")
    if legacy_upload_root and not Path(legacy_upload_root).is_dir():
        raise ValueError("The legacy upload root must already exist")
    if not storage.is_s3:
        raise ValueError("File migration requires the S3 destination")
    mode = "rw" if apply else "ro"
    engine = create_engine("sqlite://", hide_parameters=True, creator=lambda: sqlite3.connect(
        source_sqlite.as_uri() + f"?mode={mode}", uri=True, timeout=30
    ))
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE" if apply else "BEGIN")
            if not canonical_schema_tables(inspect(connection)):
                raise ValueError("Upgrade the source to the canonical Studio schema first")
            with Session(bind=connection) as session:
                owners = {
                    str(user.id) for user in session.scalars(select(User))
                    if user.external_subject and user.external_subject.strip()
                }
                plan = AssetPlan(app_data_root, legacy_upload_root, owners, legacy_origins, storage.root)
                updates = []
                for model in (ImageAsset, PresentationModel, SlideModel):
                    for record in session.scalars(select(model)):
                        row = {column.key: getattr(record, column.key) for column in model.__table__.columns}
                        try:
                            changes = transform_record_references(model.__tablename__, row, plan.transform)
                            if changes:
                                updates.append((model, row, changes))
                        except (ValueError, OSError) as exc:
                            plan.issues.append(f"{model.__tablename__}/{record.id}: {exc}")
                plan.scan_unreferenced()
                report = {
                    "applied": False,
                    "objects": [asdict(item) for item in plan.items.values()],
                    "updates": [{"table": model.__tablename__, "id": str(row["id"]), "fields": sorted(changes)} for model, row, changes in updates],
                    "issues": plan.issues, "warnings": plan.warnings,
                }
                if apply and plan.issues:
                    return report
                if apply:
                    for item in plan.items.values():
                        if file_sha256(Path(item.source)) != item.sha256:
                            raise ValueError("A source file changed after preflight; stop all writers")
                        storage.publish(item.source, item.reference, migration=True)
                    for model, row, changes in updates:
                        if "updated_at" in row:
                            changes = {**changes, "updated_at": row["updated_at"]}
                        session.execute(update(model).where(model.id == row["id"]).values(**changes), execution_options={"synchronize_session": False})
                    session.flush()
                    connection.commit()
                    report["applied"] = True
                return report
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sqlite", type=Path, required=True)
    parser.add_argument("--app-data-root", type=Path, required=True)
    parser.add_argument("--legacy-upload-root", type=Path)
    parser.add_argument("--legacy-origin", action="append", default=[])
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        report_path = args.report.resolve()
        roots = [args.app_data_root.resolve()]
        if args.legacy_upload_root:
            roots.append(args.legacy_upload_root.resolve())
        if report_path.suffix.lower() != ".json" or report_path == args.source_sqlite.resolve() or any(report_path.is_relative_to(root) for root in roots):
            raise ValueError("Choose a JSON report path outside all source roots and the source database")
        result = migrate(
            args.source_sqlite, args.app_data_root,
            AssetStorage(_read_configuration(args.env_file)),
            legacy_upload_root=args.legacy_upload_root,
            legacy_origins=args.legacy_origin, apply=args.apply,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{'Applied' if result['applied'] else 'Dry run'}: {len(result['objects'])} objects; {len(result['updates'])} row updates; {len(result['issues'])} blocking issues; {len(result['warnings'])} warnings. Source files preserved.")
        return 1 if result["issues"] else 0
    except Exception as exc:
        # S3 exceptions are translated by the adapter; never print credentials.
        parser.exit(1, f"Studio asset migration failed: {type(exc).__name__}. Inspect configuration and the source schema; no success was recorded.\n")


if __name__ == "__main__":
    raise SystemExit(main())
