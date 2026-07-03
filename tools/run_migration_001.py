"""
Migration 001 helper — quote_number column.

Run this script to check migration status. If the column is missing,
copy the SQL printed below and run it in Supabase SQL Editor:
  Project → SQL Editor → New query → paste → Run

Usage:
    python -m tools.run_migration_001
"""
from __future__ import annotations
from dotenv import load_dotenv

load_dotenv()

from database.supabase_client import get_client

db = get_client()

# Check whether quote_number column already exists
try:
    result = db.table("proposals").select("quote_number").limit(1).execute()
    has_column = True
    rows = result.data or []
    has_values = any(r.get("quote_number") is not None for r in rows)
    print("✅ Column 'quote_number' already exists in proposals.")
    if not has_values:
        print("⚠️  Column exists but no values yet — back-fill may still be needed.")
        print("   Run the UPDATE block below in the SQL Editor.")
except Exception as e:
    has_column = False
    print(f"❌ Column 'quote_number' not found ({e})")
    print()

print()
print("─" * 60)
print("SQL to run in Supabase SQL Editor (safe to run multiple times):")
print("─" * 60)
print("""
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS quote_number int;

UPDATE proposals
SET quote_number = subq.rn
FROM (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY EXTRACT(YEAR FROM created_at)
               ORDER BY created_at
           ) AS rn
    FROM proposals
    WHERE quote_number IS NULL
) subq
WHERE proposals.id = subq.id;
""")
print("─" * 60)
print("After running the SQL, proposals will be numbered PC-2026-001, PC-2026-002, etc.")
