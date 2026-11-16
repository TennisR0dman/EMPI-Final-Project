"""Run the documented SQL checks and write their result tables."""

import sqlite3
from pathlib import Path

from empi.config import SQL_DIR
from empi.csvio import write_csv
from empi.issues import ISSUE_CATALOG
from empi.sqlutil import NamedSql, load_named_sql


def _queries(kind: str) -> list[NamedSql]:
    return [
        query
        for query in load_named_sql(SQL_DIR / "data_quality_queries.sql")
        if query.kind == kind
    ]


def run_issue_queries(connection: sqlite3.Connection) -> int:
    inserted = 0
    for query in _queries("issue"):
        if query.name not in ISSUE_CATALOG:
            raise KeyError(f"SQL issue {query.name} is missing from the issue catalog")
        expected = ISSUE_CATALOG[query.name]
        for row in connection.execute(query.sql):
            if row["issue_type"] != query.name:
                raise RuntimeError(
                    f"{query.name} returned issue_type {row['issue_type']}"
                )
            if row["severity"] != expected.severity:
                raise RuntimeError(
                    f"{query.name} severity {row['severity']} does not match the catalog"
                )
            connection.execute(
                """
                INSERT INTO data_quality_issue (
                    record_id, issue_type, field_name, severity, detail
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row["record_id"],
                    row["issue_type"],
                    row["field_name"],
                    row["severity"],
                    row["detail"],
                ),
            )
            inserted += 1
    return inserted


def export_reports(connection: sqlite3.Connection, output_dir: Path) -> list[dict]:
    folder = output_dir / "query_results"
    index_rows = []
    for query in _queries("report"):
        rows = [dict(row) for row in connection.execute(query.sql)]
        columns = list(rows[0].keys()) if rows else _columns(connection, query.sql)
        write_csv(folder / f"{query.name}.csv", rows, columns)
        index_rows.append(
            {
                "name": query.name,
                "kind": query.kind,
                "row_count": len(rows),
                "purpose": query.purpose,
            }
        )
    write_csv(
        folder / "index.csv",
        index_rows,
        ("name", "kind", "row_count", "purpose"),
    )
    return index_rows


def _columns(connection: sqlite3.Connection, sql: str) -> list[str]:
    cursor = connection.execute(sql)
    return [item[0] for item in cursor.description or []]


def sql_confusion(connection: sqlite3.Connection, name: str) -> dict[str, int]:
    queries = {
        query.name: query
        for query in load_named_sql(SQL_DIR / "evaluation_queries.sql")
        if query.kind == "evaluation"
    }
    row = connection.execute(queries[name].sql).fetchone()
    return {
        "true_pairs": int(row["true_pairs"]),
        "predicted_pairs": int(row["predicted_pairs"]),
        "true_positives": int(row["true_positives"]),
    }
