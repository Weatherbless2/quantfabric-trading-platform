"""Apply AuthAdminService PostgreSQL migrations exactly once per version."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text


MIGRATIONS_DIR = Path(__file__).with_name("migrations") / "postgresql"


def main() -> None:
    database_url = os.environ.get("QF_AUTH_DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        raise RuntimeError("QF_AUTH_DATABASE_URL must point to PostgreSQL for production migrations")

    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS qf_schema_migration (
                version VARCHAR(128) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        applied = {
            row[0]
            for row in connection.execute(text("SELECT version FROM qf_schema_migration"))
        }
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name in applied:
                continue
            connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
            connection.execute(
                text("INSERT INTO qf_schema_migration (version) VALUES (:version)"),
                {"version": migration.name},
            )
            print(f"applied {migration.name}")


if __name__ == "__main__":
    main()
