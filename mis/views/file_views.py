"""
MIS File Handling Views
=======================
Views for Excel upload, template downloads, and file operations.
"""

from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["POST"])
def upload_excel(request):
    """Handle Excel file upload for bulk daily log entries (flexible headers)."""
    from ..services.manual_entry_merger import ManualEntryMerger
    
    try:
        if 'excel_file' not in request.FILES:
            messages.error(request, 'No Excel file provided')
            return redirect('mis:dashboard')

        excel_file = request.FILES['excel_file']

        # Save to a temporary file to pass to pandas importer
        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            for chunk in excel_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        merger = ManualEntryMerger()
        imported_count = merger.import_daily_logs_from_excel(temp_path)

        # Clean up temp file
        try:
            os.unlink(temp_path)
        except Exception:
            pass

        if imported_count > 0:
            messages.success(request, f'Successfully imported {imported_count} daily logs')
        else:
            messages.warning(request, 'No rows imported. Please verify headers and data formats.')

        logger.info(f"Excel upload: {imported_count} imported by {request.user}")
        return redirect('mis:dashboard')

    except Exception as e:
        logger.error(f"Error uploading Excel file: {e}", exc_info=True)
        messages.error(request, f'Error processing Excel file: {str(e)}')
        return redirect('mis:dashboard')


@login_required
@require_http_methods(["GET"])
def download_manual_template(request):
    """Generate and download the manual logs Excel template.

    Query params:
    - date: YYYY-MM-DD (defaults to today)
    - horse: vehicle/horse number string (defaults to 'MH 18 BZ 0000')
    - variant: '1' to use headers 'Date' and 'Vehicle No', else 'Log Date' and 'Horse No'
    """
    try:
        import pandas as pd
        from datetime import datetime, date as _date
        
        date_str = request.GET.get('date')
        horse_no = request.GET.get('horse', 'MH 18 BZ 0000')
        variant = request.GET.get('variant', '0') == '1'

        if date_str:
            try:
                dt = datetime.fromisoformat(date_str).date()
            except ValueError:
                messages.warning(request, 'Invalid date format; expected YYYY-MM-DD. Using today.')
                dt = _date.today()
        else:
            dt = _date.today()

        date_col = "Date" if variant else "Log Date"
        horse_col = "Vehicle No" if variant else "Horse No"

        row = {
            date_col: dt,
            horse_col: horse_no,
            "Trailer No": "TR-XXX",
            "Driver ID": "DRV-001",
            "LR": "LR-123",
            "Trailer OEM": "OEM-Brand",
            "Delivery No": "DEL-001",
            "Driver ID (Jhulwania)": "DRV-002",
            "Trailer No (Jhulwania)": "TR-YYY",
            "Horse No (Jhulwania)": "MH 18 BZ 0001",
            "Tonnage Load": 22.5,
            "Tonnage Unload": 22.0,
            "Toll Paid (Manawar to Jhulwania)": 300.0,
            "Toll Paid (Jhulwania to Dhule)": 400.0,
            "Maintenance": "OK",
        }

        df = pd.DataFrame([row])
        from io import BytesIO
        bio = BytesIO()
        # Use pandas to_excel (uses openpyxl/xlsxwriter depending on env)
        df.to_excel(bio, index=False)
        bio.seek(0)

        filename = f"manual_logs_template_{dt.isoformat()}.xlsx"
        response = HttpResponse(
            bio.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    
    except Exception as e:
        logger.error(f"Error generating manual template: {e}", exc_info=True)
        messages.error(request, f'Error generating template: {str(e)}')
        return redirect('mis:dashboard')