"""IMPORFACTORY Premium — core/database.py con DUAL CONNECTION.

Engines:
  1) BD PROPIA (imporfactory_premium):
     - blog_articulos, blog_categorias, blog_videos_youtube,
       blog_generaciones_ai, blog_visitas_diarias
     - clases_vivas, clase_inscripciones, clase_recordatorios
     - finanzas_snapshots, fotos_base_daniel

  2) BD ERP REFERENCIA (grupo_impor) read-only para:
     - alumnos, alumno_membresias (lectura de membresías activas)
     - empresa_config (read keys/configs centralizadas)
     - flujo_caja (para snapshot finanzas)
     - whatsapp_queue (escribir mensajes nuevos a la cola del ERP)

Uso:
    # BD propia (default)
    async with get_db() as db: ...

    # BD ERP (read-only mostly, write para whatsapp_queue)
    async with get_db_erp() as db: ...
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import declarative_base


# ────────────────────────────────────────
# BD PROPIA (imporfactory_premium)
# ────────────────────────────────────────
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "impor")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "imporfactory_premium")

DATABASE_URL = (
    f"mysql+aiomysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    f"?charset=utf8mb4"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia FastAPI. Usar con Depends(get_db)."""
    async with AsyncSessionLocal() as session:
        yield session


# ────────────────────────────────────────
# BD ERP (grupo_impor) — read-mostly
# ────────────────────────────────────────
ERP_DB_HOST = os.environ.get("ERP_DB_HOST", DB_HOST)
ERP_DB_PORT = int(os.environ.get("ERP_DB_PORT", DB_PORT))
ERP_DB_USER = os.environ.get("ERP_DB_USER", DB_USER)
ERP_DB_PASSWORD = os.environ.get("ERP_DB_PASSWORD", DB_PASSWORD)
ERP_DB_NAME = os.environ.get("ERP_DB_NAME", "grupo_impor")

ERP_DATABASE_URL = (
    f"mysql+aiomysql://{ERP_DB_USER}:{ERP_DB_PASSWORD}@{ERP_DB_HOST}:{ERP_DB_PORT}/{ERP_DB_NAME}"
    f"?charset=utf8mb4"
)

erp_engine = create_async_engine(
    ERP_DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

ErpAsyncSessionLocal = async_sessionmaker(
    erp_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_erp() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia FastAPI. Usar con Depends(get_db_erp).

    Solo para queries a tablas del ERP (alumnos, alumno_membresias,
    empresa_config, flujo_caja, whatsapp_queue).
    """
    async with ErpAsyncSessionLocal() as session:
        yield session


# ────────────────────────────────────────
# Base SQLAlchemy para modelos
# ────────────────────────────────────────
Base = declarative_base()
