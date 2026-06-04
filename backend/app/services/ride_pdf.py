"""
GRUPO IMPOR — Generador de RIDE (PDF) para comprobantes electrónicos SRI Ecuador.

Genera el RIDE (Representación Impresa del Documento Electrónico) usando reportlab.
Formato conforme al esquema SRI Ecuador (Acuerdo 067-2016).

Recibe el dict de la factura local + datos del comprobante (de Datil JSON o SRI XML).
"""
from __future__ import annotations
import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def generate_ride_pdf(factura_data: dict) -> bytes:
    """
    Genera el RIDE PDF de una factura electronica.

    Args:
        factura_data: dict con campos:
            - numero: str (001-003-000000120)
            - clave_acceso: str (49 digitos)
            - fecha: str (YYYY-MM-DD)
            - cliente_nombre: str
            - cliente_ruc: str
            - emisor_razon_social: str
            - emisor_ruc: str
            - emisor_direccion: str
            - subtotal: float
            - iva: float
            - total: float
            - numero_autorizacion: str (= clave_acceso para SRI)
            - fecha_autorizacion: str
            - items: list[{descripcion, cantidad, precio_unitario, subtotal}]
            - estado_sri: str

    Returns:
        bytes del PDF generado
    """
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm, mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    except ImportError as e:
        raise RuntimeError(f"reportlab no disponible: {e}")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )

    styles = getSampleStyleSheet()
    style_normal = ParagraphStyle("normal", fontSize=8, leading=10)
    style_small  = ParagraphStyle("small",  fontSize=7, leading=9)
    style_bold   = ParagraphStyle("bold",   fontSize=8, leading=10, fontName="Helvetica-Bold")
    style_title  = ParagraphStyle("title",  fontSize=10, leading=13, fontName="Helvetica-Bold", alignment=TA_CENTER)
    style_center = ParagraphStyle("center", fontSize=8, leading=10, alignment=TA_CENTER)
    style_right  = ParagraphStyle("right",  fontSize=8, leading=10, alignment=TA_RIGHT)

    # ---- Extraer datos ----
    emisor_rs    = factura_data.get("emisor_razon_social") or "GRUPO IMPOR"
    emisor_ruc   = factura_data.get("emisor_ruc") or ""
    emisor_dir   = factura_data.get("emisor_direccion") or "Quito, Ecuador"
    numero       = factura_data.get("numero") or ""
    clave        = factura_data.get("clave_acceso") or ""
    fecha        = factura_data.get("fecha") or ""
    num_aut      = factura_data.get("numero_autorizacion") or clave
    fecha_aut    = factura_data.get("fecha_autorizacion") or ""
    cliente_rs   = factura_data.get("cliente_nombre") or "Consumidor Final"
    cliente_ruc  = factura_data.get("cliente_ruc") or "9999999999999"
    subtotal     = float(factura_data.get("subtotal") or 0)
    iva          = float(factura_data.get("iva") or 0)
    total        = float(factura_data.get("total") or 0)
    items        = factura_data.get("items") or []
    estado_sri   = factura_data.get("estado_sri") or ""

    elements = []

    # ---- Cabecera: 2 columnas ----
    # Col izq: emisor | Col der: numero + clave de acceso
    header_data = [
        [
            Paragraph(f"<b>{emisor_rs}</b>", ParagraphStyle("h1", fontSize=11, fontName="Helvetica-Bold")),
            Paragraph("<b>FACTURA</b>", style_title),
        ],
        [
            Paragraph(f"RUC: {emisor_ruc}", style_normal),
            Paragraph(f"No. {numero}", style_center),
        ],
        [
            Paragraph(f"Dir: {emisor_dir}", style_small),
            Paragraph(f"<b>NÚMERO DE AUTORIZACIÓN</b>", style_center),
        ],
        [
            Paragraph("", style_normal),
            Paragraph(f'<font size="6">{num_aut}</font>', style_center),
        ],
        [
            Paragraph("", style_normal),
            Paragraph(f"Fecha Aut.: {fecha_aut}", style_small),
        ],
        [
            Paragraph("", style_normal),
            Paragraph(f"<b>AMBIENTE:</b> PRODUCCIÓN", style_center),
        ],
        [
            Paragraph("", style_normal),
            Paragraph(f"<b>EMISIÓN:</b> NORMAL", style_center),
        ],
    ]
    header_tbl = Table(header_data, colWidths=[9*cm, 9*cm])
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOX", (1,0), (1,-1), 0.5, colors.black),
        ("GRID", (1,2), (1,-1), 0.25, colors.lightgrey),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
    ]))
    elements.append(header_tbl)
    elements.append(Spacer(1, 3*mm))

    # ---- Clave de acceso (codigo de barras simulado como texto) ----
    elements.append(Paragraph(f"<b>CLAVE DE ACCESO:</b> {clave}", style_small))
    elements.append(Spacer(1, 3*mm))

    # ---- Datos del comprador ----
    comprador_data = [
        [Paragraph("<b>DATOS DEL COMPRADOR</b>", style_bold), "", ""],
        ["Razón Social:", Paragraph(cliente_rs, style_normal), ""],
        ["Identificación:", Paragraph(cliente_ruc, style_normal), f"Fecha Emisión: {fecha}"],
        ["Dirección:", Paragraph(factura_data.get("cliente_direccion", ""), style_normal), ""],
    ]
    comp_tbl = Table(comprador_data, colWidths=[3.5*cm, 9*cm, 5.5*cm])
    comp_tbl.setStyle(TableStyle([
        ("SPAN", (0,0), (-1,0)),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a237e")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("BOX", (0,0), (-1,-1), 0.5, colors.black),
        ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("FONTNAME", (0,1), (0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    elements.append(comp_tbl)
    elements.append(Spacer(1, 3*mm))

    # ---- Detalle de ítems ----
    det_headers = ["Cant.", "Código", "Descripción", "P. Unit.", "Desc.", "P. Total"]
    det_rows = [det_headers]
    for it in items:
        det_rows.append([
            str(it.get("cantidad", 1)),
            str(it.get("codigo", it.get("codigo_principal", ""))),
            it.get("descripcion", ""),
            f"${float(it.get('precio_unitario', 0)):.2f}",
            f"${float(it.get('descuento', 0)):.2f}",
            f"${float(it.get('subtotal', it.get('precio_total_sin_impuestos', 0))):.2f}",
        ])

    det_tbl = Table(det_rows, colWidths=[1.5*cm, 2.5*cm, 8*cm, 2*cm, 1.8*cm, 2.2*cm])
    det_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1a237e")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("ALIGN", (0,0), (1,-1), "CENTER"),
        ("ALIGN", (3,0), (-1,-1), "RIGHT"),
        ("BOX", (0,0), (-1,-1), 0.5, colors.black),
        ("GRID", (0,0), (-1,-1), 0.25, colors.lightgrey),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    elements.append(det_tbl)
    elements.append(Spacer(1, 3*mm))

    # ---- Totales ----
    totales_data = [
        ["", "", "SUBTOTAL IVA 15%:", f"${subtotal:.2f}"],
        ["", "", "SUBTOTAL IVA 0%:", "$0.00"],
        ["", "", "IVA 15%:", f"${iva:.2f}"],
        ["", "", "DESCUENTO:", "$0.00"],
        ["", "", Paragraph("<b>TOTAL:</b>", style_bold), Paragraph(f"<b>${total:.2f}</b>", ParagraphStyle("total_val", fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
    ]
    tot_tbl = Table(totales_data, colWidths=[5*cm, 5*cm, 5*cm, 3*cm])
    tot_tbl.setStyle(TableStyle([
        ("SPAN", (0,0), (1,-1)),
        ("ALIGN", (2,0), (3,-1), "RIGHT"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LINEBELOW", (2,-1), (3,-1), 1, colors.black),
        ("LINEABOVE", (2,-1), (3,-1), 0.5, colors.grey),
    ]))
    elements.append(tot_tbl)
    elements.append(Spacer(1, 3*mm))

    # ---- Estado SRI ----
    estado_color = "#4caf50" if "AUTORIZ" in (estado_sri or "").upper() else "#ff9800"
    elements.append(Paragraph(
        f'<font color="{estado_color}"><b>ESTADO SRI: {estado_sri}</b></font>',
        ParagraphStyle("estado", fontSize=9, fontName="Helvetica-Bold", alignment=TA_CENTER)
    ))

    # ---- Footer ----
    elements.append(Spacer(1, 5*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Paragraph(
        "Este documento es una representación impresa del comprobante electrónico. "
        "El documento original autorizado se puede verificar en www.sri.gob.ec",
        ParagraphStyle("footer", fontSize=7, leading=9, alignment=TA_CENTER, textColor=colors.grey)
    ))

    doc.build(elements)
    return buf.getvalue()
