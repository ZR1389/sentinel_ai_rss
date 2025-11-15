"""Run Phase 2 GDELT indexing migration.

Idempotent: will add columns + indexes if missing.
Safe to run multiple times.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gdelt_migrate")

SQL_FILE = Path(__file__).parent / "migrate_gdelt_phase2.sql"

def run():
    from db_utils import _get_db_connection
    sql_text = SQL_FILE.read_text()
    statements: List[str] = []
    buff = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buff.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buff))
            buff.clear()
    if buff:
        statements.append("\n".join(buff))
    applied = 0
    with _get_db_connection() as conn:
        cur = conn.cursor()
        for stmt in statements:
            try:
                cur.execute(stmt)
                applied += 1
            except Exception as e:
                logger.warning("Skip/failed statement: %s -- %s", stmt[:80], e)
    logger.info("Phase 2 migration statements attempted: %d", applied)

if __name__ == "__main__":
    run()