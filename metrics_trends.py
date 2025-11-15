"""metrics_trends.py — Persist periodic monitoring snapshots to Postgres and expose helpers.

Stores compact coverage metrics snapshots for historical trend charts.

Env:
  ENABLE_TRENDS_SNAPSHOT=true|false (default: true)
  TRENDS_SNAPSHOT_MIN=60 (minutes)
"""
from __future__ import annotations

import os
import time
import threading
from typing import Dict, Any, List
from datetime import datetime

from coverage_monitor import get_coverage_monitor

try:
    from db_utils import execute, fetch_all
except Exception:
    execute = fetch_all = None


def ensure_trends_table() -> None:
    if execute is None:
        return
    sql = """
    CREATE TABLE IF NOT EXISTS coverage_trends (
        id BIGSERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL DEFAULT now(),
        total_locations INTEGER NOT NULL,
        covered_locations INTEGER NOT NULL,
        coverage_gaps INTEGER NOT NULL,
        total_alerts_7d INTEGER NOT NULL,
        synthetic_alerts_7d INTEGER NOT NULL,
        synthetic_ratio_7d NUMERIC(6,2) NOT NULL,
        extraction_success_rate NUMERIC(6,2) NOT NULL,
        gating_rate NUMERIC(6,2) NOT NULL
    );
    """
    try:
        execute(sql, ())
    except Exception:
        pass


def snapshot_coverage_trends() -> Dict[str, Any]:
    mon = get_coverage_monitor()
    report = mon.get_comprehensive_report()
    geo = report.get("geographic_coverage", {})
    loc = report.get("location_extraction", {})
    gate = report.get("advisory_gating", {})
    row = {
        "total_locations": int(geo.get("total_locations", 0)),
        "covered_locations": int(geo.get("covered_locations", 0)),
        "coverage_gaps": int(geo.get("coverage_gaps", 0)),
        "total_alerts_7d": int(geo.get("provenance", {}).get("total_alerts_7d", 0)),
        "synthetic_alerts_7d": int(geo.get("provenance", {}).get("synthetic_alerts_7d", 0)),
        "synthetic_ratio_7d": float(geo.get("provenance", {}).get("synthetic_ratio_7d", 0.0)),
        "extraction_success_rate": float(loc.get("success_rate", 0.0)),
        "gating_rate": float(gate.get("gating_rate", 0.0)),
    }
    if execute is not None:
        try:
            execute(
                """
                INSERT INTO coverage_trends (
                    total_locations, covered_locations, coverage_gaps,
                    total_alerts_7d, synthetic_alerts_7d, synthetic_ratio_7d,
                    extraction_success_rate, gating_rate
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    row["total_locations"], row["covered_locations"], row["coverage_gaps"],
                    row["total_alerts_7d"], row["synthetic_alerts_7d"], row["synthetic_ratio_7d"],
                    row["extraction_success_rate"], row["gating_rate"],
                ),
            )
        except Exception:
            pass
    row["timestamp"] = datetime.utcnow().isoformat() + "Z"
    return row


def fetch_trends(limit: int = 168) -> List[Dict[str, Any]]:
    if fetch_all is None:
        return []
    try:
        rows = fetch_all(
            """
            SELECT ts, total_locations, covered_locations, coverage_gaps,
                   total_alerts_7d, synthetic_alerts_7d, synthetic_ratio_7d,
                   extraction_success_rate, gating_rate
            FROM coverage_trends
            ORDER BY ts DESC
            LIMIT %s
            """,
            (limit,),
        )
        out: List[Dict[str, Any]] = []
        for r in rows:
            # rows may be sequences; adapt by index
            out.append({
                "ts": r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]),
                "total_locations": int(r[1]),
                "covered_locations": int(r[2]),
                "coverage_gaps": int(r[3]),
                "total_alerts_7d": int(r[4]),
                "synthetic_alerts_7d": int(r[5]),
                "synthetic_ratio_7d": float(r[6]),
                "extraction_success_rate": float(r[7]),
                "gating_rate": float(r[8]),
            })
        return out
    except Exception:
        return []


def start_trends_snapshotter() -> None:
    if os.getenv("ENABLE_TRENDS_SNAPSHOT", "true").lower() not in ("1","true","yes","on"):
        return
    ensure_trends_table()
    interval_min = float(os.getenv("TRENDS_SNAPSHOT_MIN", "60"))
    def _loop():
        while True:
            try:
                snapshot_coverage_trends()
            except Exception:
                pass
            time.sleep(max(30.0, interval_min * 60.0))
    t = threading.Thread(target=_loop, name="trends-snapshotter", daemon=True)
    t.start()
