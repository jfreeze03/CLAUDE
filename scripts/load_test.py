#!/usr/bin/env python3
"""OVERWATCH Load Test — Simulate concurrent user sessions.

Measures warehouse credit cost and query latency under concurrent load.
Run against a test environment (not production).

Usage:
    python scripts/load_test.py --sessions 10 --duration 60

Requires: snowflake-connector-python
"""
import argparse
import time
import threading
import statistics
from datetime import datetime


def create_session(account: str, user: str, password: str, warehouse: str, role: str):
    """Create a Snowflake connection."""
    import snowflake.connector
    return snowflake.connector.connect(
        account=account,
        user=user,
        password=password,
        warehouse=warehouse,
        role=role,
        database="DBA_MAINT_DB",
        schema="OVERWATCH",
    )


# Queries that simulate typical OVERWATCH section loads
LOAD_QUERIES = [
    # Cost shell KPIs
    """SELECT warehouse_name, ROUND(SUM(credits_used), 2) AS total_credits
       FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
       WHERE start_time >= DATEADD('day', -7, CURRENT_TIMESTAMP())
       GROUP BY warehouse_name ORDER BY total_credits DESC LIMIT 15""",

    # DBA Control Room snapshot
    """SELECT COUNT_IF(state='FAILED') AS fail_count,
              COUNT_IF(execution_status='RUNNING') AS active_count
       FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
       WHERE start_time >= DATEADD('hour', -4, CURRENT_TIMESTAMP())""",

    # Alert count
    """SELECT STATUS, COUNT(*) AS cnt
       FROM DBA_MAINT_DB.OVERWATCH.OVERWATCH_ALERTS
       GROUP BY STATUS""",

    # Task failures
    """SELECT name, state, COUNT(*) AS runs
       FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
       WHERE scheduled_time >= DATEADD('day', -1, CURRENT_TIMESTAMP())
       GROUP BY name, state LIMIT 20""",

    # Warehouse metering daily
    """SELECT DATE(start_time) AS d, ROUND(SUM(credits_used), 2) AS cr
       FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
       WHERE start_time >= DATEADD('day', -30, CURRENT_TIMESTAMP())
       GROUP BY d ORDER BY d LIMIT 30""",
]


def simulate_user_session(session_id: int, conn_params: dict, duration_sec: int, results: list):
    """Simulate a single user session running queries in a loop."""
    try:
        conn = create_session(**conn_params)
        cursor = conn.cursor()
        cursor.execute(f"ALTER SESSION SET QUERY_TAG = 'OVERWATCH_LOAD_TEST:session_{session_id}'")

        start = time.time()
        query_times = []
        query_count = 0
        errors = 0

        while time.time() - start < duration_sec:
            for sql in LOAD_QUERIES:
                if time.time() - start >= duration_sec:
                    break
                try:
                    q_start = time.time()
                    cursor.execute(sql)
                    cursor.fetchall()
                    elapsed_ms = (time.time() - q_start) * 1000
                    query_times.append(elapsed_ms)
                    query_count += 1
                except Exception:
                    errors += 1
                time.sleep(0.5)  # Simulate think time

        cursor.close()
        conn.close()

        results.append({
            "session_id": session_id,
            "queries": query_count,
            "errors": errors,
            "avg_ms": statistics.mean(query_times) if query_times else 0,
            "p95_ms": sorted(query_times)[int(len(query_times) * 0.95)] if len(query_times) > 1 else 0,
            "max_ms": max(query_times) if query_times else 0,
            "duration_sec": time.time() - start,
        })
    except Exception as e:
        results.append({"session_id": session_id, "error": str(e)})


def main():
    parser = argparse.ArgumentParser(description="OVERWATCH Load Test")
    parser.add_argument("--account", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--warehouse", default="OVERWATCH_WH")
    parser.add_argument("--role", default="OVERWATCH_APP_ROLE")
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")
    args = parser.parse_args()

    conn_params = {
        "account": args.account,
        "user": args.user,
        "password": args.password,
        "warehouse": args.warehouse,
        "role": args.role,
    }

    print(f"OVERWATCH Load Test")
    print(f"  Sessions: {args.sessions}")
    print(f"  Duration: {args.duration}s")
    print(f"  Warehouse: {args.warehouse}")
    print(f"  Starting at: {datetime.now().isoformat()}")
    print("=" * 50)

    results = []
    threads = []

    for i in range(args.sessions):
        t = threading.Thread(target=simulate_user_session, args=(i, conn_params, args.duration, results))
        threads.append(t)
        t.start()
        time.sleep(0.2)  # Stagger starts

    for t in threads:
        t.join()

    # Report
    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50)

    successful = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]

    if successful:
        total_queries = sum(r["queries"] for r in successful)
        total_errors = sum(r["errors"] for r in successful)
        all_avg = statistics.mean(r["avg_ms"] for r in successful)
        all_p95 = statistics.mean(r["p95_ms"] for r in successful)

        print(f"\n  Successful sessions: {len(successful)}/{args.sessions}")
        print(f"  Total queries executed: {total_queries}")
        print(f"  Total query errors: {total_errors}")
        print(f"  Avg query latency: {all_avg:.0f}ms")
        print(f"  Avg P95 latency: {all_p95:.0f}ms")
        print(f"  Queries/sec (aggregate): {total_queries / args.duration:.1f}")

    if failed:
        print(f"\n  Failed sessions: {len(failed)}")
        for f in failed:
            print(f"    Session {f['session_id']}: {f['error'][:100]}")

    print(f"\n  Completed at: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
