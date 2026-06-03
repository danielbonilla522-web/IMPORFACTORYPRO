#!/usr/bin/env python3
"""
Cron: drena clase_recordatorios.estado=pendiente cada 5 min.
2026-05-27 Sprint 4.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # /home/ubuntu/sistema/backend
sys.path.insert(0, str(ROOT / "app"))

from dotenv import load_dotenv
load_dotenv(str(ROOT / ".env"))

from core.database import AsyncSessionLocal
from services.imporfactory_clases_service import enqueue_pending_reminders


async def main():
    async with AsyncSessionLocal() as db:
        n = await enqueue_pending_reminders(db, lookahead_min=1)
        print(f"[clases-recordatorios] OK encolados={n}")


if __name__ == "__main__":
    asyncio.run(main())
