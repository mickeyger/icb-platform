"""
Advanced PDF Generation System for Trailer Costing Reports
Supports HTML templates with precise positioning and PDF overlays
"""

import os
from io import BytesIO
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

from fastapi.responses import StreamingResponse
# Import WeasyPrint lazily - it may fail on Windows without GTK
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError) as e:
    WEASYPRINT_AVAILABLE = False
    WEASYPRINT_ERROR = str(e)

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import inch, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
import jinja2

from .templates.pdf_templates.config import get_template_config

class PDFGenerator:
    def __init__(self, template_dir: str = "templates/pdf_templates", db_session=None):
        self.template_dir = Path(template_dir)
        self.db_session = db_session
        self.template_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.template_dir),
            autoescape=jinja2.select_autoescape(['html', 'xml'])
        )

    def generate_pdf(self, trailer_name: str, data: Dict[str, Any]) -> bytes:
        """
        Generate PDF using the appropriate template for the trailer type.
        """
        template_name, config = self._get_template_config(trailer_name)

        return self.generate_pdf_from_config(template_name, config, data)

    def generate_pdf_from_config(self, template_name: Optional[str], config: Dict[str, Any], data: Dict[str, Any]) -> bytes:
        """
        Generate PDF from an explicit template configuration.
        """
        template_name = template_name or config.get('template', 'default.html')

        if config.get('use_overlay', False) and config.get('background_pdf'):
            # Use overlay method for precise positioning
            return self._generate_overlay_pdf(template_name, config, data)
        else:
            # Use HTML template method
            return self._generate_html_pdf(template_name, data)

    def _get_template_config(self, trailer_name: str) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Get template configuration for a trailer type from database.
        Falls back to file-based config if database not available.
        """
        if self.db_session:
            from .database import PDFTemplate, TrailerType
            import json

            # Try to find template by trailer type name
            trailer_type = self.db_session.query(TrailerType).filter(
                TrailerType.name.ilike(f"%{trailer_name}%")
            ).first()

            if trailer_type:
                candidates = self.db_session.query(PDFTemplate).filter_by(is_active=True).order_by(PDFTemplate.updated_at.desc(), PDFTemplate.id.desc()).all()

                for candidate in candidates:
                    config = json.loads(candidate.template_data)
                    linked_trailer_ids = config.get("trailer_type_ids") or []
                    if trailer_type.id in linked_trailer_ids:
                        return config.get('template', 'default.html'), config

                for candidate in candidates:
                    if candidate.trailer_type_id == trailer_type.id:
                        config = json.loads(candidate.template_data)
                        return config.get('template', 'default.html'), config

        # Fallback to file-based config
        return get_template_config(trailer_name)

    def _generate_html_pdf(self, template_name: str, data: Dict[str, Any]) -> bytes:
        """
        Generate PDF from HTML template using WeasyPrint.
        Falls back to ReportLab if WeasyPrint fails (e.g., GTK missing on Windows).
        """
        we_error = None
        
        # Try WeasyPrint first if it's available
        if WEASYPRINT_AVAILABLE:
            try:
                from weasyprint import HTML, CSS
                template = self.template_env.get_template(template_name)
                html_content = template.render(**data)

                # Add custom CSS for precise positioning if needed
                custom_css = CSS(string="""
                    @page {
                        size: A4;
                        margin: 0.5in;
                    }
                """)

                # Generate PDF
                pdf_bytes = HTML(string=html_content).write_pdf(stylesheets=[custom_css])
                return pdf_bytes

            except Exception as e:
                # WeasyPrint failed - likely due to missing GTK libraries on Windows
                we_error = e
                print(f"WeasyPrint failed: {e}")
                print("Falling back to ReportLab PDF generation...")
        else:
            we_error = WEASYPRINT_ERROR
            print(f"WeasyPrint not available: {WEASYPRINT_ERROR}")
            print("Using ReportLab PDF generation...")
        
        # Fall back to ReportLab
        try:
            return self._generate_reportlab_pdf(data)
        except Exception as rl_error:
            print(f"ReportLab fallback also failed: {rl_error}")
            raise Exception(f"PDF generation failed: Both WeasyPrint and ReportLab failed. WeasyPrint: {we_error}")

    def _generate_reportlab_pdf(self, data: Dict[str, Any]) -> bytes:
        """
        Generate PDF using ReportLab (pure Python, no GTK required).
        This is a fallback when WeasyPrint fails on Windows.
        """
        from datetime import datetime
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4,
                               rightMargin=0.5*inch, leftMargin=0.5*inch,
                               topMargin=0.5*inch, bottomMargin=0.5*inch)
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a1a2e'),
            spaceAfter=20,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        elements.append(Paragraph("TRAILER COST REPORT", title_style))
        elements.append(Spacer(1, 0.3*inch))
        
        # Trailer Type
        trailer_name = data.get('trailer_name', 'N/A')
        elements.append(Paragraph(f"<b>Trailer Type:</b> {trailer_name}", styles['Normal']))
        elements.append(Spacer(1, 0.1*inch))
        
        # Record ID and Date
        record_id = data.get('record_id', 'N/A')
        created_at = data.get('created_at', datetime.now())
        if isinstance(created_at, str):
            created_at_str = created_at
        else:
            created_at_str = created_at.strftime('%Y-%m-%d %H:%M') if created_at else 'N/A'
        
        elements.append(Paragraph(f"<b>Record ID:</b> {record_id}", styles['Normal']))
        elements.append(Paragraph(f"<b>Generated:</b> {created_at_str}", styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))
        
        # Dimensions
        dimensions = data.get('dimensions', {})
        if dimensions:
            elements.append(Paragraph("<b>Dimensions:</b>", styles['Heading3']))
            dim_data = [
                ['Length', f"{dimensions.get('length', 0)} m"],
                ['Width', f"{dimensions.get('width', 0)} m"],
                ['Height', f"{dimensions.get('height', 0)} m"],
            ]
            dim_table = Table(dim_data, colWidths=[2*inch, 2*inch])
            dim_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ]))
            elements.append(dim_table)
            elements.append(Spacer(1, 0.2*inch))
        
        # Costing Result
        result = data.get('result', {})
        if result:
            elements.append(Paragraph("<b>Costing Summary:</b>", styles['Heading3']))
            
            result_data = []
            
            # Add various cost items if they exist
            if 'subtotal' in result or 'material_cost' in result:
                subtotal = result.get('subtotal') or result.get('material_cost', 0)
                result_data.append(['Subtotal', f"R {float(subtotal):,.2f}"])
            
            if 'labor_cost' in result:
                result_data.append(['Labor Cost', f"R {float(result['labor_cost']):,.2f}"])
            
            if 'overhead' in result:
                result_data.append(['Overhead', f"R {float(result['overhead']):,.2f}"])
            
            if 'profit_margin' in result:
                result_data.append(['Profit Margin', f"R {float(result['profit_margin']):,.2f}"])
            
            # Grand total - highlighted
            grand_total = result.get('grand_total', 0)
            result_data.append(['<b>GRAND TOTAL</b>', f"<b>R {float(grand_total):,.2f}</b>"])
            
            if result_data:
                result_table = Table(result_data, colWidths=[3*inch, 2*inch])
                result_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
                    ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#e8f4f8')),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                    ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('FONTSIZE', (0, -1), (-1, -1), 12),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#1a1a2e')),
                ]))
                elements.append(result_table)
        
        elements.append(Spacer(1, 0.5*inch))
        
        # Footer
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER
        )
        elements.append(Paragraph("Generated by Trailer Costing System", footer_style))
        
        # Build PDF
        doc.build(elements)
        buffer.seek(0)
        return buffer.getvalue()

    def _generate_overlay_pdf(self, template_name: str, config: Dict[str, Any], data: Dict[str, Any]) -> bytes:
        """
        Generate PDF by overlaying data on existing PDF template.
        """
        background_pdf = config.get('background_pdf')
        overlay_positions = config.get('overlay_positions', {})
        static_texts = config.get('static_text') or []

        if not background_pdf or not os.path.exists(background_pdf):
            # Fallback to HTML if background PDF not found
            return self._generate_html_pdf(template_name, data)

        try:
            # Read background PDF
            reader = PdfReader(background_pdf)
            writer = PdfWriter()
            writer.clone_document_from_reader(reader)

            # Build a map of field values from data
            form_fields = self._get_pdf_form_fields(reader)
            field_values = self._get_fillable_field_values(data)
            styled_overlay_fields = {
                field_name
                for field_name, pos in overlay_positions.items()
                if pos.get('font_size') is not None or pos.get('color')
            }
            form_field_values = {
                key: value for key, value in field_values.items()
                if key not in styled_overlay_fields
            }

            # Update form fields and overlay positions against the cloned writer pages
            for page_num, page in enumerate(writer.pages):
                if form_field_values and form_fields:
                    try:
                        writer.update_page_form_field_values(page, form_field_values, auto_regenerate=False)
                    except Exception as exc:
                        print(f"Could not update PDF form fields on page {page_num}: {exc}")

                # Add overlay data to this page if positions defined and if the field is not already a form field
                page_has_dynamic = page_num in [pos['page'] for pos in overlay_positions.values()]
                page_has_static  = any(int(item.get('page', 0)) == page_num for item in static_texts)
                if page_has_dynamic or page_has_static:
                    self._add_overlay_to_page(
                        writer, page_num, overlay_positions, data, form_fields,
                        static_texts=static_texts,
                    )

            if form_fields:
                writer.set_need_appearances_writer()

            output_buffer = BytesIO()
            writer.write(output_buffer)
            output_buffer.seek(0)
            return output_buffer.getvalue()

        except Exception as e:
            print(f"Overlay PDF generation error: {e}")
            # Fallback to HTML
            return self._generate_html_pdf(template_name, data)

    def _get_pdf_form_fields(self, reader: PdfReader) -> Dict[str, Any]:
        """
        Return all form field names from a PDF reader.
        """
        try:
            fields = reader.get_fields() or {}
            return {name: field for name, field in fields.items()}
        except Exception:
            return {}

    def _add_overlay_to_page(self, writer: PdfWriter, page_num: int,
                           positions: Dict[str, Dict], data: Dict[str, Any], form_fields: Dict[str, Any],
                           static_texts: list = None):
        """
        Add overlay data to a specific page.
        """
        # Create overlay PDF
        page = writer.pages[page_num]
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)
        overlay_buffer = BytesIO()
        c = canvas.Canvas(overlay_buffer, pagesize=(page_width, page_height))

        # Draw static-text whiteouts + replacement text first so dynamic fields draw on top.
        for item in (static_texts or []):
            if int(item.get('page', 0)) != page_num:
                continue
            text = str(item.get('text', '') or '')
            x = float(item.get('x', 0))
            y = float(item.get('y', 0))  # baseline, points from bottom
            try:
                font_size = max(6, min(72, float(item.get('font_size', 10))))
            except Exception:
                font_size = 10
            color_hex   = str(item.get('color', '#000000') or '#000000')
            bg_hex      = item.get('bg_color', '#FFFFFF')
            align       = item.get('align', 'left')
            pad_x       = float(item.get('pad_x', 2))
            pad_y       = float(item.get('pad_y', 2))
            box_w_raw   = item.get('width')
            box_h_raw   = item.get('height')

            font_name = "Helvetica-Bold"
            try:
                text_w = c.stringWidth(text, font_name, font_size) if text else 0
            except Exception:
                text_w = 0
            text_h = font_size  # approx ascent height

            box_w = float(box_w_raw) if box_w_raw not in (None, '', 0) else (text_w + 2 * pad_x)
            box_h = float(box_h_raw) if box_h_raw not in (None, '', 0) else (text_h + 2 * pad_y)

            if align == 'center':
                box_x = x - box_w / 2
                text_x = x
            elif align == 'right':
                box_x = x - box_w
                text_x = x
            else:
                box_x = x
                text_x = x + pad_x
            box_y = y - pad_y  # rectangle starts slightly below baseline

            # Whiteout rectangle (skip if bg explicitly disabled)
            if bg_hex:
                try:
                    c.setFillColor(colors.HexColor(str(bg_hex)))
                except Exception:
                    c.setFillColorRGB(1, 1, 1)
                c.rect(box_x, box_y, box_w, box_h, stroke=0, fill=1)

            # Replacement text on top
            try:
                c.setFillColor(colors.HexColor(color_hex))
            except Exception:
                c.setFillColorRGB(0, 0, 0)
            c.setFont(font_name, font_size)
            if align == 'center':
                c.drawCentredString(text_x, y, text)
            elif align == 'right':
                c.drawRightString(text_x, y, text)
            else:
                c.drawString(text_x, y, text)

        # Add data at specified positions
        for field_name, pos_config in positions.items():
            if pos_config['page'] == page_num:
                has_style_override = pos_config.get('font_size') is not None or bool(pos_config.get('color'))
                if form_fields and field_name in form_fields and not has_style_override:
                    continue

                x = pos_config['x']  # points from left
                y = pos_config['y']  # points from bottom

                # Get value from data
                value = self._get_field_value(field_name, data)

                if value:
                    # Set font and color
                    font_size = 10
                    try:
                        font_size = max(6, min(72, float(pos_config.get('font_size', 10))))
                    except Exception:
                        font_size = 10

                    color_value = pos_config.get('color', '#000000')
                    try:
                        c.setFillColor(colors.HexColor(str(color_value)))
                    except Exception:
                        c.setFillColorRGB(0, 0, 0)

                    c.setFont("Helvetica-Bold", font_size)

                    # Draw the text with alignment
                    align = pos_config.get('align', 'left')
                    if align == 'center':
                        c.drawCentredString(x, y, str(value))
                    elif align == 'right':
                        c.drawRightString(x, y, str(value))
                    else:
                        c.drawString(x, y, str(value))

        c.save()
        overlay_buffer.seek(0)

        # Merge overlay with the page
        overlay_reader = PdfReader(overlay_buffer)
        if len(overlay_reader.pages) > 0:
            overlay_page = overlay_reader.pages[0]
            current_page = writer.pages[page_num]
            current_page.merge_page(overlay_page)

    def _get_fillable_field_values(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a mapping for fillable PDF fields from data.
        """
        from datetime import datetime

        def get_customer_value(*keys):
            customer = data.get('customer') or {}
            result = data.get('result') or {}
            for key in keys:
                if customer.get(key):
                    return customer.get(key)
                if result.get(key):
                    return result.get(key)
            return ''

        def fmt_number(value):
            try:
                return f"{float(value):,.2f}"
            except Exception:
                return str(value)

        values = {
            'trailer_type': data.get('trailer_name', ''),
            'costing_id': str(data.get('record_id', '')),
            'costing_number': str(data.get('record_id', '')),
            'length': fmt_number(data.get('dimensions', {}).get('length', 0)),
            'width': fmt_number(data.get('dimensions', {}).get('width', 0)),
            'height': fmt_number(data.get('dimensions', {}).get('height', 0)),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'date_stamp': datetime.now().strftime('%Y-%m-%d'),
            'price': fmt_number(data.get('result', {}).get('selling_price') or data.get('result', {}).get('grand_total', 0)),
            'grand_total': fmt_number(data.get('result', {}).get('grand_total', 0)),
            'selling_price': fmt_number(data.get('result', {}).get('selling_price') or data.get('result', {}).get('grand_total', 0)),
            'customer_name': get_customer_value('name', 'customer_name'),
            'customer_email': get_customer_value('email', 'customer_email'),
            'customer_telephone': get_customer_value('telephone', 'customer_telephone'),
            'customer_phone': get_customer_value('telephone', 'customer_telephone', 'customer_phone'),
        }

        # Only return fields that are non-empty
        return {k: v for k, v in values.items() if v is not None}

    def _get_field_value(self, field_name: str, data: Dict[str, Any]) -> str:
        """
        Get the value for a field from the data dictionary.
        """
        def get_customer_value(*keys):
            customer = data.get('customer') or {}
            result = data.get('result') or {}
            for key in keys:
                if customer.get(key):
                    return customer.get(key)
                if result.get(key):
                    return result.get(key)
            return ''

        field_mapping = {
            'trailer_type': lambda d: d.get('trailer_name', ''),
            'costing_id': lambda d: str(d.get('record_id', '')),
            'costing_number': lambda d: str(d.get('record_id', '')),
            'length': lambda d: f"{d.get('dimensions', {}).get('length', 0)} m",
            'width': lambda d: f"{d.get('dimensions', {}).get('width', 0)} m",
            'height': lambda d: f"{d.get('dimensions', {}).get('height', 0)} m",
            'price': lambda d: f"R {(d.get('result', {}).get('selling_price') or d.get('result', {}).get('grand_total', 0)):,.2f}",
            'grand_total': lambda d: f"R {d.get('result', {}).get('grand_total', 0):,.2f}",
            'selling_price': lambda d: f"R {(d.get('result', {}).get('selling_price') or d.get('result', {}).get('grand_total', 0)):,.2f}",
            'date': lambda d: __import__('datetime').datetime.now().strftime('%Y-%m-%d'),
            'customer_name': lambda d: get_customer_value('name', 'customer_name'),
            'customer_email': lambda d: get_customer_value('email', 'customer_email'),
            'customer_telephone': lambda d: get_customer_value('telephone', 'customer_telephone'),
            'customer_phone': lambda d: get_customer_value('telephone', 'customer_telephone', 'customer_phone'),
        }

        if field_name in field_mapping:
            return field_mapping[field_name](data)

        return ""

# Global PDF generator instance
pdf_generator = PDFGenerator()

def generate_trailer_pdf(trailer_name: str, record_id: int, dimensions: Dict,
                        result: Dict, created_at, user=None, customer=None, db_session=None) -> bytes:
    """
    Main function to generate trailer PDF report.
    """
    data = {
        'trailer_name': trailer_name,
        'record_id': record_id,
        'dimensions': dimensions,
        'result': result,
        'created_at': created_at,
        'user': user,
        'customer': customer,
    }

    # Create PDF generator with database session if provided
    generator = PDFGenerator(db_session=db_session)
    return generator.generate_pdf(trailer_name, data)