#!/usr/bin/env python3
"""
Cron: recalcula snapshot de finanzas IMPORFACTORY cada 6h.

Path: /home/ubuntu/sistema/backend/app/scripts/cron_finanzas_snapshot.py
Crontab: 0 */6 * * * ubuntu /home/ubuntu/sistema/backend/venv/bin/python3 ... >> /var/log/imporfactory_finanzas.log 2>&1

2026-05-27 Sprint 3.
"""
from __future__ import annotations

import asyncio
import os
import sys

from pathlib import Path

# bootstrap path para que `from services.X import ...` funcione
ROOT = Path(__file__).resolve().parents[2]   # /home/ubuntu/sistema/backend
sys.path.insert(0, str(ROOT / "app"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / ".env"))

from core.database import AsyncSessionLocal
from services.imporfactory_finanzas_service import compute_snapshot, upsert_snapshot


async def main():
    async with AsyncSessionLocal() as db:
        snap = await compute_snapshot(db, empresa_id=5)
        snap_id = await upsert_snapshot(db, snap)
        print(f"[finanzas-snapshot] OK fecha={snap['fecha']} id={snap_id} "
              f"mrr={snap['mrr']:.2f} alumnos_activos={snap['alumnos_activos']} "
              f"breakdown={snap['breakdown_membresias_json']}")


if __name__ == "__main__":
    asyncio.run(main())
