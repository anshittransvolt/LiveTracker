import requests
import pandas as pd
from django.http import HttpResponse
from django.conf import settings
from ..alertService.geofence import point_in_geofences

def dashboard_report_dataframe():
    """
    Fetch latest point for each vehicle from the API and return a DataFrame for dashboard report.
    """
    domain = settings.SMARTFASTAPI_DOMAIN
    headers = {}
    if hasattr(settings, 'SMARTFASTAPI_ACCESS_KEY') and settings.SMARTFASTAPI_ACCESS_KEY:
        headers['x-api-key'] = settings.SMARTFASTAPI_ACCESS_KEY
    api_url = f"{domain}/vehicleiplt?limit=6"
    response = requests.get(api_url, headers=headers, timeout=15)
    if response.status_code != 200:
        raise Exception("Failed to fetch vehicle data")
    points = response.json()
    # Group by vehicle_no, keep only latest point (assuming sorted by last_connected desc)
    latest_by_vehicle = {}
    for p in points:
        vno = p.get('vehicle_no')
        if not vno:
            continue
        t = p.get('last_connected')
        if vno not in latest_by_vehicle or (t and latest_by_vehicle[vno].get('last_connected', '') < t):
            latest_by_vehicle[vno] = p
    rows = []
    for vno, p in latest_by_vehicle.items():
        start_odo = p.get('start_odometer')
        end_odo = p.get('end_odometer')
        try:
            distance = float(end_odo) - float(start_odo)
        except Exception:
            distance = ''
        latlon = p.get('gps_location')
        geofence = ''
        if latlon:
            try:
                lat, lon = map(float, latlon.split(','))
                gf = point_in_geofences(lat, lon)
                manawar_geofences = {"Tarpulien", "Charging Point", "Loading Area", "Weighing Area"}
                if gf in manawar_geofences:
                    geofence = f"Manawar {gf}"
                else:
                    geofence = gf if gf else ''
            except Exception:
                geofence = ''
        rows.append({
            'vehicle_no': vno,
            'vehicle_status': p.get('vehicle_status', ''),
            'soc': p.get('soc', ''),
            'distance_travelled': distance,
            'last_connected': p.get('last_connected', ''),
            'gps_location': latlon,
            'geofence': geofence,
            'model': 'Rhino 5536e',
            'variant': '6X4TT',
        })
    df = pd.DataFrame(rows)
    return df

def download_dashboard_report(request):
    """
    Download Excel dashboard report for all vehicles (latest point per vehicle).
    """
    try:
        df = dashboard_report_dataframe()
    except Exception as e:
        return HttpResponse(f"Failed to fetch dashboard data: {e}", status=400)
    import io
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # Write DataFrame to Excel
        df.to_excel(writer, index=False)

        # Auto-fit column widths based on content and headers
        try:
            workbook = writer.book
            # Default sheet name used by pandas when not specified
            sheet_name = list(writer.sheets.keys())[0]
            worksheet = writer.sheets[sheet_name]

            for col_num, col_name in enumerate(df.columns):
                # Compute max length from data
                try:
                    series = df[col_name].fillna("").astype(str)
                    max_content_len = int(series.map(len).max()) if not df.empty else 0
                except Exception:
                    max_content_len = 0

                header_len = len(str(col_name))
                max_len = max(max_content_len, header_len)

                padding = 2
                min_width = 8
                max_width = 40

                # Wider minimums for date/time-like columns
                if "Time" in col_name or "Date" in col_name:
                    min_width = max(min_width, 18)
                    max_len = max(max_len, 18)

                # Numeric-ish columns
                if ("KM" in col_name) or ("SOC" in col_name) or ("KWH" in col_name) or ("Distance" in col_name):
                    min_width = max(min_width, 10)

                width = max(min_width, min(max_len + padding, max_width))
                worksheet.set_column(col_num, col_num, width)
        except Exception:
            # Non-fatal; if autofit fails, export still works
            pass
    output.seek(0)
    excel_data = output.read()
    response = HttpResponse(excel_data, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="dashboard_report.xlsx"'
    return response
