"""
IMPORFACTORY Premium — Servicio de clases en vivo.

Lógica de negocio para masterclasses:
  - Inscripción masiva por filtro de membresía
  - Programación automática de 3 recordatorios (24h / 1h / 5min antes)
  - Encolado en whatsapp_queue cuando llega la hora del recordatorio
  - Render de templates de mensaje con variables {nombre}, {clase}, {zoom_url}, {hora_local}

2026-05-27 Sprint 4.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── Templates de mensaje (editables en futuro via /mensajeria/templates) ──
TEMPLATES_RECORDATORIO = {
    "24h": (
        "Hola {nombre} 🎓\n"
        "Recordatorio: mañana {hora_local} es la masterclass *{clase}* con {instructor}.\n"
        "🔗 Link Zoom: {zoom_url}\n\n"
        "Te esperamos!"
    ),
    "1h": (
        "Hola {nombre} ⏰\n"
        "En *1 hora* arranca la masterclass *{clase}*.\n"
        "Prepárate con cuaderno y agua.\n"
        "🔗 Link: {zoom_url}"
    ),
    "5min": (
        "🔴 EN VIVO en 5 min: *{clase}*\n"
        "Entra aquí 👉 {zoom_url}"
    ),
    "post_grabacion": (
        "Hola {nombre} 🎥\n"
        "Aquí tienes la grabación de *{clase}*:\n"
        "{grabacion_url}\n\n"
        "La puedes ver cuando quieras desde tu cuenta."
    ),
}


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Normaliza teléfono al formato internacional sin + ni espacios."""
    if not phone:
        return None
    clean = "".join(c for c in str(phone) if c.isdigit())
    if not clean:
        return None
    # Si arranca con 0 o 5 dígitos, asumir Ecuador (+593)
    if len(clean) == 10 and clean.startswith("0"):
        clean = "593" + clean[1:]
    elif len(clean) == 9:
        clean = "593" + clean
    return clean if len(clean) >= 10 else None


async def schedule_reminders_for_clase(db: AsyncSession, clase_id: int) -> int:
    """Genera filas en clase_recordatorios para cada inscrito × cada tipo (24h/1h/5min).

    Idempotente: usa UNIQUE (clase_id, alumno_id, tipo). Re-llamar no duplica.
    Retorna número de filas insertadas (nuevas).
    """
    # Cargar clase
    clase = (await db.execute(text("""
        SELECT id, fecha_inicio FROM clases_vivas WHERE id = :id
    """), {"id": clase_id})).mappings().first()
    if not clase:
        return 0

    fecha_inicio: datetime = clase["fecha_inicio"]

    # Calcular timestamps de cada recordatorio
    times = {
        "24h": fecha_inicio - timedelta(hours=24),
        "1h": fecha_inicio - timedelta(hours=1),
        "5min": fecha_inicio - timedelta(minutes=5),
    }

    # Listar inscritos
    inscritos = (await db.execute(text("""
        SELECT alumno_id FROM clase_inscripciones WHERE clase_id = :cid
    """), {"cid": clase_id})).mappings().all()

    inserted = 0
    for r in inscritos:
        for tipo, programado in times.items():
            try:
                res = await db.execute(text("""
                    INSERT IGNORE INTO clase_recordatorios
                        (clase_id, alumno_id, tipo, estado, programado_para)
                    VALUES (:cid, :aid, :tipo, 'pendiente', :prog)
                """), {"cid": clase_id, "aid": r["alumno_id"], "tipo": tipo, "prog": programado})
                inserted += res.rowcount
            except Exception:
                pass
    await db.commit()
    return inserted


async def inscribir_masivo(db: AsyncSession, db_erp: AsyncSession, clase_id: int, filtro_membresia: list[str]) -> int:
    """Inscribe todos los alumnos con alguna membresía activa de los tipos dados.

    DBs separadas: alumno_membresias vive en el ERP (db_erp), clase_inscripciones
    en la BD propia (db). Por eso se hace en dos pasos (no INSERT...SELECT cross-DB).

    Returns: número de inscripciones nuevas.
    """
    if not filtro_membresia:
        return 0

    placeholders = ",".join([f":t{i}" for i in range(len(filtro_membresia))])
    params = {f"t{i}": tipo for i, tipo in enumerate(filtro_membresia)}

    # 1) Alumnos elegibles desde el ERP (grupo_impor)
    alumno_rows = (await db_erp.execute(text(f"""
        SELECT DISTINCT am.alumno_id
        FROM alumno_membresias am
        WHERE am.activa = 1 AND am.tipo IN ({placeholders})
    """), params)).mappings().all()

    # 2) Insertar inscripciones en la BD propia (ignora duplicados por UNIQUE)
    inserted = 0
    for r in alumno_rows:
        res = await db.execute(text("""
            INSERT IGNORE INTO clase_inscripciones (clase_id, alumno_id, inscripcion_modo)
            VALUES (:cid, :aid, 'masiva')
        """), {"cid": clase_id, "aid": r["alumno_id"]})
        inserted += res.rowcount
    await db.commit()

    # 3) Re-programar recordatorios (todo BD propia)
    await schedule_reminders_for_clase(db, clase_id)
    return inserted


async def enqueue_pending_reminders(db: AsyncSession, db_erp: AsyncSession, lookahead_min: int = 1) -> int:
    """Drena clase_recordatorios.estado=pendiente AND programado_para<=NOW()+lookahead.

    DBs separadas: clase_recordatorios/clases_vivas en BD propia (db); alumnos y
    whatsapp_queue en el ERP (db_erp). Se resuelve en pasos sin JOIN cross-DB.

    Inserta en whatsapp_queue con trigger_origen='clase_recordatorio'.
    Returns: número de mensajes encolados.
    """
    # 1) Recordatorios pendientes + datos de clase (BD propia, sin JOIN alumnos)
    rows = (await db.execute(text("""
        SELECT cr.id AS recordatorio_id, cr.clase_id, cr.alumno_id, cr.tipo, cr.programado_para,
               cv.titulo, cv.instructor, cv.fecha_inicio, cv.zoom_join_url, cv.grabacion_url
        FROM clase_recordatorios cr
        JOIN clases_vivas cv ON cv.id = cr.clase_id
        WHERE cr.estado = 'pendiente'
          AND cr.programado_para <= DATE_ADD(NOW(), INTERVAL :look MINUTE)
          AND cv.estado IN ('programada','en_vivo','finalizada')
        LIMIT 500
    """), {"look": lookahead_min})).mappings().all()

    if not rows:
        return 0

    # 2) Datos de alumnos desde el ERP (batch)
    alumno_ids = list({r["alumno_id"] for r in rows})
    alumnos_map = {}
    if alumno_ids:
        ph = ",".join(f":a{i}" for i in range(len(alumno_ids)))
        ap = {f"a{i}": aid for i, aid in enumerate(alumno_ids)}
        arows = (await db_erp.execute(text(f"""
            SELECT id, nombre, whatsapp, email FROM alumnos WHERE id IN ({ph})
        """), ap)).mappings().all()
        alumnos_map = {a["id"]: a for a in arows}

    encolados = 0
    for r in rows:
        alumno = alumnos_map.get(r["alumno_id"]) or {}
        telefono_norm = normalize_phone(alumno.get("whatsapp"))
        template = TEMPLATES_RECORDATORIO.get(r["tipo"], "")
        if not telefono_norm or not template:
            await db.execute(text("""
                UPDATE clase_recordatorios SET estado='no_aplica', error_msg='sin telefono o template'
                WHERE id = :id
            """), {"id": r["recordatorio_id"]})
            continue

        mensaje = template.format(
            nombre=(alumno.get("nombre") or "alumno").split(" ")[0],
            clase=r["titulo"],
            instructor=r["instructor"] or "Daniel",
            zoom_url=r["zoom_join_url"] or "(link pendiente)",
            grabacion_url=r["grabacion_url"] or "(grabación pendiente)",
            hora_local=r["fecha_inicio"].strftime("%H:%M") if r["fecha_inicio"] else "",
        )

        jid = telefono_norm + "@s.whatsapp.net"
        try:
            insert_res = await db_erp.execute(text("""
                INSERT INTO whatsapp_queue
                    (empresa_id, alumno_id, telefono, jid, mensaje, wacli_store,
                     scheduled_at, trigger_origen, contexto_json)
                VALUES
                    (5, :aid, :tel, :jid, :msg, '/home/ubuntu/.wacli-imporfactory',
                     NOW(), 'clase_recordatorio', :ctx)
            """), {
                "aid": r["alumno_id"], "tel": telefono_norm, "jid": jid, "msg": mensaje,
                "ctx": json.dumps({"clase_id": r["clase_id"], "tipo": r["tipo"], "recordatorio_id": r["recordatorio_id"]}),
            })
            await db_erp.commit()
            queue_id = insert_res.lastrowid

            await db.execute(text("""
                UPDATE clase_recordatorios
                SET estado='encolado', mensaje_wa_queue_id = :qid
                WHERE id = :id
            """), {"qid": queue_id, "id": r["recordatorio_id"]})
            encolados += 1
        except Exception as e:
            await db.execute(text("""
                UPDATE clase_recordatorios SET estado='fallo', error_msg=:err WHERE id = :id
            """), {"err": str(e)[:500], "id": r["recordatorio_id"]})

    await db.commit()
    return encolados


async def crear_clase(db: AsyncSession, db_erp: AsyncSession, payload: dict, created_by: int = 1) -> int:
    """Crea una clase nueva y retorna su id."""
    res = await db.execute(text("""
        INSERT INTO clases_vivas
            (empresa_id, titulo, descripcion, instructor, fecha_inicio, duracion_min,
             zoom_meeting_id, zoom_join_url, zoom_password,
             max_asistentes, estado, dirigida_a, slug, notas_internas, created_by)
        VALUES
            (5, :titulo, :descripcion, :instructor, :fecha_inicio, :duracion_min,
             :zoom_meeting_id, :zoom_join_url, :zoom_password,
             :max_asistentes, 'programada', :dirigida_a, :slug, :notas, :cby)
    """), {
        "titulo": payload["titulo"],
        "descripcion": payload.get("descripcion"),
        "instructor": payload.get("instructor", "Daniel Bonilla"),
        "fecha_inicio": payload["fecha_inicio"],
        "duracion_min": payload.get("duracion_min", 60),
        "zoom_meeting_id": payload.get("zoom_meeting_id"),
        "zoom_join_url": payload.get("zoom_join_url"),
        "zoom_password": payload.get("zoom_password"),
        "max_asistentes": payload.get("max_asistentes", 1000),
        "dirigida_a": json.dumps(payload.get("dirigida_a") or []),
        "slug": payload.get("slug"),
        "notas": payload.get("notas_internas"),
        "cby": created_by,
    })
    await db.commit()
    clase_id = res.lastrowid

    # Si vienen membresías de audiencia, inscribir masivo inmediatamente
    if payload.get("dirigida_a"):
        await inscribir_masivo(db, db_erp, clase_id, payload["dirigida_a"])

    return clase_id


async def listar_clases(db: AsyncSession, estado: Optional[str] = None, limit: int = 100) -> list[dict]:
    """Lista clases con conteo de inscritos."""
    where = "WHERE cv.empresa_id = 5"
    params = {"limit": limit}
    if estado:
        where += " AND cv.estado = :estado"
        params["estado"] = estado

    rows = (await db.execute(text(f"""
        SELECT cv.id, cv.titulo, cv.instructor, cv.fecha_inicio, cv.duracion_min,
               cv.estado, cv.zoom_join_url, cv.max_asistentes, cv.dirigida_a,
               (SELECT COUNT(*) FROM clase_inscripciones WHERE clase_id = cv.id) AS inscritos,
               (SELECT COUNT(*) FROM clase_recordatorios WHERE clase_id = cv.id AND estado='pendiente') AS recordatorios_pendientes
        FROM clases_vivas cv
        {where}
        ORDER BY cv.fecha_inicio DESC
        LIMIT :limit
    """), params)).mappings().all()
    return [dict(r) for r in rows]


async def get_clase_detalle(db: AsyncSession, db_erp: AsyncSession, clase_id: int) -> Optional[dict]:
    """Detalle completo de una clase: datos + inscritos + recordatorios.

    DBs separadas: clase_inscripciones en BD propia, datos de alumnos en el ERP.
    """
    clase = (await db.execute(text("""
        SELECT * FROM clases_vivas WHERE id = :id
    """), {"id": clase_id})).mappings().first()
    if not clase:
        return None

    inscritos_raw = (await db.execute(text("""
        SELECT ci.alumno_id, ci.fecha_inscripcion, ci.asistio, ci.minutos_asistidos,
               ci.inscripcion_modo
        FROM clase_inscripciones ci
        WHERE ci.clase_id = :id
        ORDER BY ci.fecha_inscripcion DESC
        LIMIT 500
    """), {"id": clase_id})).mappings().all()

    # Enriquecer con datos de alumnos desde el ERP (batch)
    alumno_ids = list({r["alumno_id"] for r in inscritos_raw})
    alumnos_map = {}
    if alumno_ids:
        ph = ",".join(f":a{i}" for i in range(len(alumno_ids)))
        ap = {f"a{i}": aid for i, aid in enumerate(alumno_ids)}
        arows = (await db_erp.execute(text(f"""
            SELECT id, nombre, email, whatsapp FROM alumnos WHERE id IN ({ph})
        """), ap)).mappings().all()
        alumnos_map = {a["id"]: a for a in arows}

    inscritos = []
    for r in inscritos_raw:
        a = alumnos_map.get(r["alumno_id"]) or {}
        d = dict(r)
        d["nombre"] = a.get("nombre")
        d["email"] = a.get("email")
        d["whatsapp"] = a.get("whatsapp")
        inscritos.append(d)

    recordatorios_stats = (await db.execute(text("""
        SELECT tipo, estado, COUNT(*) AS n
        FROM clase_recordatorios
        WHERE clase_id = :id
        GROUP BY tipo, estado
    """), {"id": clase_id})).mappings().all()

    return {
        "clase": dict(clase),
        "inscritos": inscritos,
        "recordatorios_stats": [dict(r) for r in recordatorios_stats],
    }
