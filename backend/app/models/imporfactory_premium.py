"""
Modelos SQLAlchemy para IMPORFACTORY Premium (empresa_id=5).

Sprint 2 — 2026-05-27. Acompañan la migración imporfactory_premium_001.sql.
Side-effect import desde main.py para que SQLAlchemy los registre en metadata.

NOTA: usamos los mismos patrones del ERP legacy (declarative_base de Base,
servidor MySQL aiomysql). NO crear sesiones aquí — el handler obtiene
una desde core.database.get_db().
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Boolean,
    ForeignKey, Index, UniqueConstraint, Enum, JSON, DECIMAL
)
from sqlalchemy.orm import relationship

from models.models import Base


# ════════════════════════════════════════════════════════════
# CLASES EN VIVO
# ════════════════════════════════════════════════════════════

class ClaseViva(Base):
    """Masterclass / webinar en vivo (Zoom)."""
    __tablename__ = "clases_vivas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(Integer, nullable=False, default=5, index=True)
    titulo = Column(String(220), nullable=False)
    descripcion = Column(Text, nullable=True)
    instructor = Column(String(120), nullable=False, default="Daniel Bonilla")
    fecha_inicio = Column(DateTime, nullable=False)
    duracion_min = Column(Integer, nullable=False, default=60)

    zoom_meeting_id = Column(String(80), nullable=True)
    zoom_join_url = Column(String(500), nullable=True)
    zoom_password = Column(String(40), nullable=True)
    zoom_start_url = Column(String(500), nullable=True)

    max_asistentes = Column(Integer, nullable=False, default=1000)
    grabacion_url = Column(String(500), nullable=True)
    grabacion_password = Column(String(40), nullable=True)

    estado = Column(
        Enum("programada", "en_vivo", "finalizada", "cancelada", name="clase_estado_enum"),
        nullable=False,
        default="programada",
    )
    dirigida_a = Column(JSON, nullable=True)
    imagen_portada_url = Column(String(500), nullable=True)
    slug = Column(String(120), nullable=True, unique=True)
    notas_internas = Column(Text, nullable=True)

    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    inscripciones = relationship("ClaseInscripcion", back_populates="clase", cascade="all, delete-orphan")
    recordatorios = relationship("ClaseRecordatorio", back_populates="clase", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_clases_fecha_estado", "fecha_inicio", "estado"),
    )


class ClaseInscripcion(Base):
    """Inscripción de un alumno a una clase en vivo."""
    __tablename__ = "clase_inscripciones"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clase_id = Column(Integer, ForeignKey("clases_vivas.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, nullable=False, index=True)
    fecha_inscripcion = Column(DateTime, default=datetime.utcnow)
    inscripcion_modo = Column(
        Enum("auto", "manual", "masiva", name="inscripcion_modo_enum"),
        nullable=False, default="auto",
    )
    asistio = Column(
        Enum("no", "si", "parcial", "no_registrado", name="asistio_enum"),
        nullable=False, default="no_registrado",
    )
    minutos_asistidos = Column(Integer, nullable=False, default=0)
    zoom_user_email = Column(String(150), nullable=True)
    joined_at = Column(DateTime, nullable=True)
    left_at = Column(DateTime, nullable=True)

    clase = relationship("ClaseViva", back_populates="inscripciones")

    __table_args__ = (
        UniqueConstraint("clase_id", "alumno_id", name="uq_clase_alumno"),
    )


class ClaseRecordatorio(Base):
    """Recordatorio programado para enviar via WhatsApp."""
    __tablename__ = "clase_recordatorios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clase_id = Column(Integer, ForeignKey("clases_vivas.id", ondelete="CASCADE"), nullable=False)
    alumno_id = Column(Integer, nullable=False)
    tipo = Column(
        Enum("24h", "1h", "5min", "post_grabacion", name="recordatorio_tipo_enum"),
        nullable=False,
    )
    estado = Column(
        Enum("pendiente", "encolado", "enviado", "fallo", "no_aplica", name="recordatorio_estado_enum"),
        nullable=False, default="pendiente",
    )
    mensaje_wa_queue_id = Column(Integer, nullable=True)
    programado_para = Column(DateTime, nullable=False)
    enviado_en = Column(DateTime, nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    clase = relationship("ClaseViva", back_populates="recordatorios")

    __table_args__ = (
        UniqueConstraint("clase_id", "alumno_id", "tipo", name="uq_recordatorio"),
        Index("ix_recordatorio_pendiente", "estado", "programado_para"),
    )


# ════════════════════════════════════════════════════════════
# BLOG (SEO + LLM)
# ════════════════════════════════════════════════════════════

class BlogCategoria(Base):
    """Categoría editorial del blog."""
    __tablename__ = "blog_categorias"

    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(Integer, nullable=False, default=5)
    slug = Column(String(80), nullable=False, unique=True)
    nombre = Column(String(120), nullable=False)
    descripcion = Column(Text, nullable=True)
    icon = Column(String(8), nullable=True)
    color = Column(String(16), nullable=True, default="#0EA5E9")
    seo_titulo = Column(String(200), nullable=True)
    seo_descripcion = Column(String(300), nullable=True)
    orden = Column(Integer, nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)


class BlogArticulo(Base):
    """Artículo del blog editorial (SEO + LLM optimization)."""
    __tablename__ = "blog_articulos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(Integer, nullable=False, default=5, index=True)
    slug = Column(String(220), nullable=False, unique=True)
    titulo = Column(String(260), nullable=False)
    subtitulo = Column(String(300), nullable=True)
    contenido_md = Column(Text, nullable=True)
    contenido_html = Column(Text, nullable=True)

    miniatura_url = Column(String(500), nullable=True)
    miniatura_alt = Column(String(200), nullable=True)

    autor_id = Column(Integer, nullable=True)
    autor_nombre_publico = Column(String(120), nullable=False, default="Equipo IMPORFACTORY")
    categoria_id = Column(Integer, ForeignKey("blog_categorias.id"), nullable=True)

    estado = Column(
        Enum("borrador", "revision", "programado", "publicado", "archivado", name="articulo_estado_enum"),
        nullable=False, default="borrador",
    )
    fecha_publicacion = Column(DateTime, nullable=True)

    seo_titulo = Column(String(200), nullable=True)
    seo_descripcion = Column(String(300), nullable=True)
    seo_keywords = Column(JSON, nullable=True)
    seo_canonical_url = Column(String(500), nullable=True)
    seo_og_image = Column(String(500), nullable=True)
    schema_org = Column(JSON, nullable=True)

    llm_optimization_score = Column(Integer, nullable=True)
    llm_citations_estimadas = Column(JSON, nullable=True)

    tiempo_lectura_min = Column(Integer, nullable=True)
    vistas = Column(Integer, nullable=False, default=0)
    vistas_30d = Column(Integer, nullable=False, default=0)

    tags = Column(JSON, nullable=True)
    faqs_json = Column(JSON, nullable=True)
    referencias_json = Column(JSON, nullable=True)

    generado_con_ai = Column(Boolean, nullable=False, default=False)
    revisado_humano = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    categoria = relationship("BlogCategoria")

    __table_args__ = (
        Index("ix_articulo_estado_fecha", "estado", "fecha_publicacion"),
        Index("ix_articulo_categoria_estado", "categoria_id", "estado"),
    )


class BlogVideoYoutube(Base):
    """Video YouTube espejado / programado."""
    __tablename__ = "blog_videos_youtube"

    id = Column(Integer, primary_key=True, autoincrement=True)
    articulo_id = Column(Integer, ForeignKey("blog_articulos.id"), nullable=True)
    empresa_id = Column(Integer, nullable=False, default=5)
    video_id_yt = Column(String(40), nullable=True, unique=True)
    youtube_channel_id = Column(String(60), nullable=True)
    titulo = Column(String(260), nullable=False)
    descripcion = Column(Text, nullable=True)
    thumbnail_url = Column(String(500), nullable=True)
    duracion_seg = Column(Integer, nullable=True)
    estado = Column(
        Enum("borrador", "programado", "publicado", "privado", "no_listado", "eliminado",
             name="video_estado_enum"),
        nullable=False, default="borrador",
    )
    fecha_publicacion = Column(DateTime, nullable=True)
    fecha_programada = Column(DateTime, nullable=True)
    script_md = Column(Text, nullable=True)
    storyboard_json = Column(JSON, nullable=True)
    tags_yt = Column(JSON, nullable=True)
    views = Column(Integer, nullable=False, default=0)
    likes = Column(Integer, nullable=False, default=0)
    comments = Column(Integer, nullable=False, default=0)
    last_stats_sync = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BlogGeneracionAI(Base):
    """Registro auditable de cada llamada AI (Claude, DALL-E) con costo."""
    __tablename__ = "blog_generaciones_ai"

    id = Column(Integer, primary_key=True, autoincrement=True)
    articulo_id = Column(Integer, ForeignKey("blog_articulos.id"), nullable=True)
    video_id = Column(Integer, ForeignKey("blog_videos_youtube.id"), nullable=True)
    tipo = Column(
        Enum("miniatura", "texto", "outline", "seo_meta", "schema_org",
             "video_script", "optimizacion_llm", "reescribir",
             name="generacion_tipo_enum"),
        nullable=False,
    )
    prompt = Column(Text, nullable=True)
    modelo_usado = Column(String(80), nullable=True)
    parametros_json = Column(JSON, nullable=True)
    resultado_url = Column(String(500), nullable=True)
    resultado_texto = Column(Text, nullable=True)
    costo_usd = Column(DECIMAL(8, 4), nullable=True)
    tokens_input = Column(Integer, nullable=True)
    tokens_output = Column(Integer, nullable=True)
    duracion_ms = Column(Integer, nullable=True)
    generado_en = Column(DateTime, default=datetime.utcnow)
    generado_por_id = Column(Integer, nullable=True)
    aceptado = Column(Boolean, nullable=False, default=False)


# ════════════════════════════════════════════════════════════
# FINANZAS
# ════════════════════════════════════════════════════════════

class FinanzasSnapshot(Base):
    """Snapshot diario de KPIs financieros (cache calculado por cron)."""
    __tablename__ = "finanzas_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    empresa_id = Column(Integer, nullable=False, default=5, index=True)
    fecha = Column(Date, nullable=False)

    mrr = Column(DECIMAL(12, 2), nullable=True)
    arr = Column(DECIMAL(12, 2), nullable=True)
    ingresos_mes = Column(DECIMAL(12, 2), nullable=True)
    ingresos_mes_pasado = Column(DECIMAL(12, 2), nullable=True)
    gastos_mes = Column(DECIMAL(12, 2), nullable=True)
    utilidad = Column(DECIMAL(12, 2), nullable=True)
    margen_pct = Column(DECIMAL(6, 3), nullable=True)
    churn_rate_30d = Column(DECIMAL(6, 3), nullable=True)
    churn_rate_90d = Column(DECIMAL(6, 3), nullable=True)
    ltv = Column(DECIMAL(12, 2), nullable=True)
    cac_estimado = Column(DECIMAL(12, 2), nullable=True)
    alumnos_activos = Column(Integer, nullable=True)
    alumnos_nuevos_mes = Column(Integer, nullable=True)
    alumnos_vencidos_30d = Column(Integer, nullable=True)
    alumnos_proximos_vencer_30d = Column(Integer, nullable=True)
    cuentas_por_cobrar = Column(DECIMAL(12, 2), nullable=True)
    suscripciones_stripe_activas = Column(Integer, nullable=True)
    breakdown_membresias_json = Column(JSON, nullable=True)
    costo_ai_30d = Column(DECIMAL(10, 4), nullable=False, default=0)
    calculado_en = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("empresa_id", "fecha", name="uq_fin_empresa_fecha"),
    )
