"""
Small additive schema upgrades for existing databases. create_all() makes new
tables but never adds columns to tables that already exist.
"""
from sqlalchemy import inspect, text

# (table, column, SQL type) - nullable columns only, so old rows stay valid
NEW_COLUMNS = [
    ("users", "gender", "VARCHAR(10)"),
]


def add_missing_columns(sync_conn) -> None:
    inspector = inspect(sync_conn)
    for table, column, sql_type in NEW_COLUMNS:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
