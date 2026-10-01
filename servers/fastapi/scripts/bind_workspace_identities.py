"""Use a temporary DB and an explicit mapping to move owners to scoped identity.

Default is read-only. User UUIDs and deck/file ownership remain unchanged.
"""
import argparse
import json
from pathlib import Path
import uuid

from sqlalchemy import create_engine, select, update
from models.sql.user import User
from api.v1.auth.workspace_jwt import workspace_identity


def bind_identities(connection, mappings: list[dict], *, apply=False):
    changes = []
    owners, targets = set(), set()
    for item in mappings:
        owner_id = uuid.UUID(item["owner_id"])
        identity = workspace_identity(item.get("issuer"), item["organization"], item["subject"])
        if identity is None or not isinstance(item.get("legacy_subject"), str):
            raise ValueError("Invalid explicit identity mapping")
        target = identity.external_key
        if owner_id in owners or target in targets:
            raise ValueError("Duplicate owner or target mapping")
        owners.add(owner_id)
        targets.add(target)
        owner = connection.execute(select(User.__table__).where(User.id == owner_id)).mappings().one_or_none()
        if owner is None or owner["is_superuser"]:
            raise ValueError("Only an existing ordinary Workspace owner can be bound")
        if owner["external_subject"] not in (item["legacy_subject"], target):
            raise ValueError("Owner does not match the asserted prior binding")
        conflict = connection.execute(select(User.id).where(User.external_subject == target, User.id != owner_id)).first()
        if conflict:
            raise ValueError("Target identity is already bound to another owner")
        changes.append((owner_id, owner["external_subject"], target))
    if apply:
        for owner_id, old, target in changes:
            result = connection.execute(update(User).where(User.id == owner_id, User.external_subject == old).values(external_subject=target))
            if result.rowcount != 1:
                raise ValueError("Identity changed concurrently; mapping rolled back")
    return {"mapped_owners": len(changes), "apply": apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    mappings = json.loads(args.mapping.read_text(encoding="utf-8"))
    if not isinstance(mappings, list):
        raise ValueError("Mapping must be an array")
    engine = create_engine(args.database_url, hide_parameters=True)
    try:
        with engine.begin() as connection:
            print(json.dumps(bind_identities(connection, mappings, apply=args.apply)))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
