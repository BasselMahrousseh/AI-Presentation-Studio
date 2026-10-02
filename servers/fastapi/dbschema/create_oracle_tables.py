"""Create Studio tables on Oracle. Does not run Alembic.

Print SQL for SQL*Plus / SQL Developer:

    python -m dbschema.create_oracle_tables --sql

Apply the same statements with the configured Oracle user:

    python -m dbschema.create_oracle_tables --apply
"""

import argparse
import sys

from sqlalchemy.dialects import oracle
from sqlalchemy.schema import CreateIndex, CreateTable

from dbschema.oracle_v2 import build_metadata


def ddl_statements() -> list[str]:
    dialect = oracle.dialect()
    metadata = build_metadata(include_tracker=False)
    statements = []
    for table in metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        for index in sorted(table.indexes, key=lambda item: item.name):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip())
    return statements


def render_client_sql() -> str:
    header = (
        "-- Studio presentation tables. Run as the configured Oracle user.\n"
        "-- Fresh schema only. The API also creates any missing tables on startup.\n"
    )
    return header + "\n\n".join(statement + ";" for statement in ddl_statements()) + "\n"


def apply_schema() -> None:
    from sqlalchemy import create_engine, text

    from utils.db_utils import get_database_url_and_connect_args, to_sync_sqlalchemy_url
    from utils.environment import load_studio_environment
    from utils.oracle_thick import ensure_oracle_thick_mode

    load_studio_environment()
    ensure_oracle_thick_mode()
    database_url, _connect_args = get_database_url_and_connect_args()
    engine = create_engine(to_sync_sqlalchemy_url(database_url), hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("SELECT 1 FROM DUAL"))
            for statement in ddl_statements():
                connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render or apply Studio Oracle tables")
    parser.add_argument("--sql", action="store_true", help="print the client SQL")
    parser.add_argument("--apply", action="store_true", help="create the tables on Oracle")
    args = parser.parse_args(argv)
    if args.apply:
        apply_schema()
        print("Oracle Studio tables created", flush=True)
        return 0
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.write(render_client_sql())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
