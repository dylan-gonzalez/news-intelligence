#!/usr/bin/env python3
"""
Inspect the SQLite database schema, tables, columns, and sample records.
"""

import sqlite3
import os
import json

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_platform.db")

def inspect_database():
    if not os.path.exists(DB_FILE):
        print(f"[!] Database file not found at: {DB_FILE}")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("=" * 80)
    print(f" DATABASE SCHEMA INSPECTION: {os.path.basename(DB_FILE)}")
    print("=" * 80)

    # 1. List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
    tables = [row["name"] for row in cursor.fetchall()]

    for table in tables:
        # Get row count
        cursor.execute(f"SELECT COUNT(*) as count FROM {table};")
        row_count = cursor.fetchone()["count"]

        print(f"\n📁 TABLE: [{table.upper()}] ({row_count} total rows)")
        print("-" * 80)

        # Get table columns info (PRAGMA table_info)
        # cid, name, type, notnull, dflt_value, pk
        cursor.execute(f"PRAGMA table_info({table});")
        columns = cursor.fetchall()
        
        print(f"  {'#':<3} {'Column Name':<24} {'Type':<14} {'Nullable':<10} {'Primary Key'}")
        print(f"  {'-'*3} {'-'*24} {'-'*14} {'-'*10} {'-'*11}")
        for col in columns:
            col_id = col["cid"]
            name = col["name"]
            data_type = col["type"] or "ANY"
            nullable = "NO" if col["notnull"] else "YES"
            pk = "YES (PK)" if col["pk"] else ""
            print(f"  {col_id:<3} {name:<24} {data_type:<14} {nullable:<10} {pk}")

        # Show 1-2 sample rows
        cursor.execute(f"SELECT * FROM {table} LIMIT 2;")
        samples = cursor.fetchall()
        if samples:
            print(f"\n  🔍 Sample Record:")
            first = dict(samples[0])
            for k, v in first.items():
                val_str = str(v)
                if len(val_str) > 80:
                    val_str = val_str[:77] + "..."
                print(f"     • {k:<18}: {val_str}")

    # 2. Indexes
    print("\n" + "=" * 80)
    print(" ⚡ INDEXES")
    print("=" * 80)
    cursor.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL;")
    indexes = cursor.fetchall()
    for idx in indexes:
        print(f"  • {idx['name']} on [{idx['tbl_name']}]")

if __name__ == "__main__":
    inspect_database()
