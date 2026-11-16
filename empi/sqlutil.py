"""Load the named SQL files. Each query is one statement with a header comment."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NamedSql:
    name: str
    kind: str
    purpose: str
    sql: str


_HEADER = re.compile(r"^--\s*(name|kind|purpose):\s*(.*)$")


def load_named_sql(path: Path) -> list[NamedSql]:
    text = path.read_text(encoding="utf-8")
    chunks = re.split(r"(?=^-- name:)", text, flags=re.MULTILINE)
    queries: list[NamedSql] = []
    for chunk in chunks:
        stripped = chunk.strip()
        if not stripped.startswith("-- name:"):
            continue
        meta = {"name": "", "kind": "", "purpose": ""}
        body: list[str] = []
        for line in stripped.splitlines():
            match = _HEADER.match(line)
            if match and not body:
                meta[match.group(1)] = match.group(2).strip()
            else:
                body.append(line)
        sql = "\n".join(body).strip().rstrip(";").strip()
        if not meta["name"] or not sql:
            raise ValueError(f"Incomplete SQL block in {path}")
        queries.append(NamedSql(meta["name"], meta["kind"], meta["purpose"], sql))
    if not queries:
        raise ValueError(f"No named SQL in {path}")
    return queries
