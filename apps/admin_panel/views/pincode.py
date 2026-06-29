import os
import csv
import json
import time
import re
import zipfile
import xml.etree.ElementTree as ET
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.core.files.storage import FileSystemStorage
from django.core.paginator import Paginator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.conf import settings

from apps.admin_panel.decorators import admin_login_required
from apps.home.models.pincode import Pincode
from apps.admin_panel.models.pincode_import_log import PincodeImportLog

def parse_xlsx(file_path):
    rows = []
    with zipfile.ZipFile(file_path, 'r') as zip_ref:
        # 1. Parse shared strings
        shared_strings = []
        try:
            ss_data = zip_ref.read('xl/sharedStrings.xml')
            root = ET.fromstring(ss_data)
            for elem in root.iter():
                if '}' in elem.tag:
                    elem.tag = elem.tag.split('}', 1)[1]
            for si in root.findall('.//si'):
                text = ""
                for t in si.findall('.//t'):
                    if t.text:
                        text += t.text
                shared_strings.append(text)
        except KeyError:
            pass

        # 2. Parse sheet1
        sheet_data = zip_ref.read('xl/worksheets/sheet1.xml')
        root = ET.fromstring(sheet_data)
        for elem in root.iter():
            if '}' in elem.tag:
                elem.tag = elem.tag.split('}', 1)[1]

        headers = None
        for row in root.findall('.//row'):
            row_data = []
            for cell in row.findall('./c'):
                cell_type = cell.get('t')
                val_el = cell.find('./v')
                val = val_el.text if val_el is not None else ""
                
                if cell_type == 's' and val:
                    try:
                        val = shared_strings[int(val)]
                    except (IndexError, ValueError):
                        val = ""
                row_data.append(val.strip())
            
            if not row_data:
                continue
            
            if headers is None:
                headers = row_data
                continue
            
            if len(row_data) < len(headers):
                row_data.extend([""] * (len(headers) - len(row_data)))
            row_dict = dict(zip(headers, row_data[:len(headers)]))
            rows.append(row_dict)
            
    return rows

def stream_csv(file_path):
    with open(file_path, mode='r', encoding='utf-8-sig', errors='ignore') as f:
        reader = csv.reader(f)
        headers = None
        for row in reader:
            if not row:
                continue
            if headers is None:
                headers = [h.strip() for h in row]
                continue
            row_data = [d.strip() for d in row]
            if len(row_data) < len(headers):
                row_data.extend([""] * (len(headers) - len(row_data)))
            yield dict(zip(headers, row_data[:len(headers)]))

def map_headers(lower_headers):
    lookup = {
        'pincode': ['pincode', 'pin', 'pin_code', 'postal_code', 'postalcode', 'zip'],
        'state': ['state', 'state_name', 'statename'],
        'district': ['district', 'district_name', 'districtname'],
        'latitude': ['latitude', 'lat'],
        'longitude': ['longitude', 'lng', 'lon', 'long'],
        'office_name': ['office_name', 'officename', 'office', 'area', 'locality', 'place'],
        'city': ['city', 'town', 'village'],
        'taluk': ['taluk', 'taluka', 'tehsil', 'sub_district'],
    }
    
    reverse_map = {}
    for canonical, aliases in lookup.items():
        for alias in aliases:
            reverse_map[alias] = canonical
            
    header_index = {}
    for h in lower_headers:
        normalized = h.lower().strip().replace(' ', '_').replace('-', '_')
        if normalized in reverse_map and reverse_map[normalized] not in header_index:
            header_index[reverse_map[normalized]] = h
            
    for req in ['pincode', 'state', 'district', 'latitude', 'longitude']:
        if req not in header_index:
            return None
            
    return header_index

@admin_login_required
def index(request):
    search = request.GET.get('search', '')
    state = request.GET.get('state', '')
    district = request.GET.get('district', '')
    
    query = Pincode.objects.all()
    if search:
        query = query.filter(Q(pincode__icontains=search) | Q(office_name__icontains=search))
    if state:
        query = query.filter(state=state)
    if district:
        query = query.filter(district=district)
        
    pincodes_list = query.order_by('state', 'district', 'pincode')
    
    paginator = Paginator(pincodes_list, 50)
    page_number = request.GET.get('page', 1)
    pincodes = paginator.get_page(page_number)
    
    states = Pincode.objects.values_list('state', flat=True).distinct().order_by('state')
    
    districts_query = Pincode.objects.values_list('district', flat=True).distinct().order_by('district')
    if state:
        districts_query = districts_query.filter(state=state)
    districts = list(districts_query)
    
    stats = {
        'total': Pincode.objects.count(),
        'states': Pincode.objects.values('state').distinct().count(),
        'districts': Pincode.objects.values('district').distinct().count(),
    }
    
    import_logs = PincodeImportLog.objects.order_by('-created_at')[:10]
    
    context = {
        'pincodes': pincodes,
        'states': states,
        'districts': districts,
        'stats': stats,
        'importLogs': import_logs,
        'search': search,
        'state': state,
        'district': district,
    }
    return render(request, 'admin/pincode_manager.html', context)

@admin_login_required
def upload(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed.'}, status=405)
    
    uploaded_file = request.FILES.get('file')
    if not uploaded_file:
        return JsonResponse({'success': False, 'message': 'No file uploaded.'}, status=400)
        
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ['.csv', '.xlsx', '.xls', '.txt']:
        return JsonResponse({'success': False, 'message': 'Invalid file format. Only CSV and XLSX are supported.'}, status=422)
        
    # Save file
    os.makedirs(os.path.join(settings.MEDIA_ROOT, 'pincode_imports'), exist_ok=True)
    fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'pincode_imports'))
    filename = f"pincode_import_{int(time.time())}{ext}"
    saved_name = fs.save(filename, uploaded_file)
    full_path = fs.path(saved_name)
    
    try:
        state_district_map = {}
        total_rows = 0
        
        if ext == '.xlsx':
            rows = parse_xlsx(full_path)
            if not rows:
                fs.delete(saved_name)
                return JsonResponse({'success': False, 'message': 'File is empty.'}, status=422)
            headers = [h.lower() for h in rows[0].keys()]
            mapped = map_headers(headers)
            if not mapped:
                fs.delete(saved_name)
                return JsonResponse({'success': False, 'message': 'Could not detect required columns (pincode, state, district, latitude, longitude).'}, status=422)
            
            for row in rows:
                state = row.get(mapped['state'], '').strip()
                district = row.get(mapped['district'], '').strip()
                pincode = row.get(mapped['pincode'], '').strip()
                if not state or not pincode:
                    continue
                total_rows += 1
                if state not in state_district_map:
                    state_district_map[state] = {}
                state_district_map[state][district] = state_district_map[state].get(district, 0) + 1
        else:
            with open(full_path, mode='r', encoding='utf-8-sig', errors='ignore') as f:
                reader = csv.reader(f)
                first_row = next(reader, None)
                if not first_row:
                    fs.delete(saved_name)
                    return JsonResponse({'success': False, 'message': 'File is empty.'}, status=422)
                headers = [h.strip().lower() for h in first_row]
                mapped = map_headers(headers)
                if not mapped:
                    fs.delete(saved_name)
                    return JsonResponse({'success': False, 'message': 'Could not detect required columns (pincode, state, district, latitude, longitude).'}, status=422)
                
                for row in reader:
                    if not row:
                        continue
                    row_data = [d.strip() for d in row]
                    if len(row_data) < len(headers):
                        row_data.extend([""] * (len(headers) - len(row_data)))
                    row_dict = dict(zip(headers, row_data[:len(headers)]))
                    
                    state = row_dict.get(mapped['state'].lower(), '').strip()
                    district = row_dict.get(mapped['district'].lower(), '').strip()
                    pincode = row_dict.get(mapped['pincode'].lower(), '').strip()
                    if not state or not pincode:
                        continue
                    total_rows += 1
                    if state not in state_district_map:
                        state_district_map[state] = {}
                    state_district_map[state][district] = state_district_map[state].get(district, 0) + 1
                    
        if total_rows == 0:
            fs.delete(saved_name)
            return JsonResponse({'success': False, 'message': 'No valid rows found in file.'}, status=422)
            
        admin_user = 'Admin'
        admin_id = request.session.get('admin_id')
        if admin_id:
            try:
                from apps.admin_panel.models.admin_auth import Admin
                admin_obj = Admin.objects.get(id=admin_id)
                admin_user = admin_obj.username or 'Admin'
            except Exception:
                pass
                
        log = PincodeImportLog.objects.create(
            filename=saved_name,
            status='pending',
            total_rows=total_rows,
            available_states=state_district_map,
            imported_by=admin_user
        )
        
        return JsonResponse({
            'success': True,
            'log_id': log.id,
            'total_rows': total_rows,
            'state_district_map': state_district_map
        })
        
    except Exception as e:
        fs.delete(saved_name)
        return JsonResponse({'success': False, 'message': f'File processing failed: {str(e)}'}, status=500)

@admin_login_required
def import_data(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method is allowed.'}, status=405)
        
    try:
        body = json.loads(request.body)
        log_id = body.get('log_id')
        selected_states = body.get('selected_states', [])
        selected_districts = body.get('selected_districts', [])
    except Exception:
        return JsonResponse({'success': False, 'message': 'Invalid payload.'}, status=400)
        
    if not log_id or not selected_states:
        return JsonResponse({'success': False, 'message': 'Log ID and selected states are required.'}, status=422)
        
    try:
        log = PincodeImportLog.objects.get(id=log_id)
    except PincodeImportLog.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Import log not found.'}, status=404)
        
    if log.status not in ['pending', 'failed']:
        return JsonResponse({'success': False, 'message': 'This import has already been processed.'}, status=422)
        
    log.status = 'processing'
    log.selected_states = selected_states
    log.selected_districts = selected_districts
    log.started_at = timezone.now()
    log.save()
    
    file_path = os.path.join(settings.MEDIA_ROOT, 'pincode_imports', log.filename)
    ext = os.path.splitext(log.filename)[1].lower()
    
    imported = 0
    skipped = 0
    failed = 0
    failed_details = []
    chunk_size = 500
    batch = []
    
    try:
        if ext == '.xlsx':
            rows = parse_xlsx(file_path)
            headers = [h.lower() for h in rows[0].keys()]
            mapped = map_headers(headers)
            if not mapped:
                raise ValueError("Could not detect required columns.")
            get_val = lambda row, key: str(row.get(mapped[key], '')).strip()
            row_iterable = ((i, row) for i, row in enumerate(rows, 1))
        else:
            rows = list(stream_csv(file_path))
            headers = [h.lower() for h in rows[0].keys()]
            mapped = map_headers(headers)
            if not mapped:
                raise ValueError("Could not detect required columns.")
            get_val = lambda row, key: str(row.get(mapped[key].lower(), '')).strip()
            row_iterable = ((i, row) for i, row in enumerate(rows, 1))
            
        for row_index, row in row_iterable:
            state = get_val(row, 'state')
            district = get_val(row, 'district')
            pincode = get_val(row, 'pincode')
            lat = get_val(row, 'latitude')
            lng = get_val(row, 'longitude')
            name = get_val(row, 'office_name') or get_val(row, 'city')
            taluk = get_val(row, 'taluk')
            
            if state not in selected_states:
                skipped += 1
                continue
            if selected_districts and district not in selected_districts:
                skipped += 1
                continue
                
            if not pincode or not state or not lat or not lng:
                failed += 1
                if len(failed_details) < 50:
                    failed_details.append(f"Row {row_index}: Missing required field")
                continue
                
            if not re.match(r'^[1-9]\d{5}$', pincode):
                failed += 1
                if len(failed_details) < 50:
                    failed_details.append(f"Row {row_index}: Invalid pincode — {pincode}")
                continue
                
            try:
                lat_val = float(lat)
                lng_val = float(lng)
            except ValueError:
                failed += 1
                if len(failed_details) < 50:
                    failed_details.append(f"Row {row_index}: Invalid lat/lng (not numeric)")
                continue
                
            if lat_val < -90 or lat_val > 90 or lng_val < -180 or lng_val > 180:
                failed += 1
                if len(failed_details) < 50:
                    failed_details.append(f"Row {row_index}: Lat/Lng out of valid range ({lat}, {lng})")
                continue
                
            batch.append(Pincode(
                pincode=pincode,
                office_name=name or district,
                district=district,
                state=state,
                latitude=round(lat_val, 8),
                longitude=round(lng_val, 8),
                taluk=taluk if taluk else None
            ))
            imported += 1
            
            if len(batch) >= chunk_size:
                Pincode.objects.bulk_create(
                    batch,
                    update_conflicts=True,
                    update_fields=['office_name', 'district', 'state', 'latitude', 'longitude', 'taluk', 'updated_at'],
                    unique_fields=['pincode']
                )
                batch = []
                
        if batch:
            Pincode.objects.bulk_create(
                batch,
                update_conflicts=True,
                update_fields=['office_name', 'district', 'state', 'latitude', 'longitude', 'taluk', 'updated_at'],
                unique_fields=['pincode']
            )
            
        log.status = 'completed'
        log.imported_rows = imported
        log.skipped_rows = skipped
        log.failed_rows = failed
        log.failed_details = failed_details
        log.completed_at = timezone.now()
        log.save()
        
        return JsonResponse({
            'success': True,
            'imported': imported,
            'skipped': skipped,
            'failed': failed,
            'message': f"Import complete! {imported} pincodes imported, {skipped} skipped, {failed} failed."
        })
        
    except Exception as e:
        log.status = 'failed'
        log.save()
        return JsonResponse({'success': False, 'message': f"Import failed: {str(e)}"}, status=500)

@admin_login_required
def sample_download(request):
    csv_content = (
        "state,district,office_name,taluk,pincode,latitude,longitude\n"
        "Gujarat,Ahmedabad,Satellite,Ahmedabad,380015,23.0305,72.5066\n"
        "Gujarat,Surat,Adajan,Surat,395009,21.2028,72.8304\n"
        "Maharashtra,Mumbai,Andheri East,Mumbai,400069,19.1135,72.8697\n"
    )
    response = HttpResponse(csv_content, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="pincode_sample.csv"'
    return response

@admin_login_required
def export_data(request):
    state = request.GET.get('state')
    query = Pincode.objects.all()
    if state:
        query = query.filter(state=state)
    rows = query.order_by('state', 'district', 'pincode')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="pincodes_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['pincode', 'office_name', 'district', 'state', 'taluk', 'latitude', 'longitude'])
    for r in rows:
        writer.writerow([
            r.pincode,
            r.office_name,
            r.district,
            r.state,
            r.taluk or '',
            r.latitude,
            r.longitude
        ])
    return response

@admin_login_required
def delete_by_state(request):
    if request.method in ['DELETE', 'POST']:
        state = request.POST.get('state')
        if not state and request.body:
            try:
                state = json.loads(request.body).get('state')
            except Exception:
                pass
        if not state:
            return JsonResponse({'success': False, 'message': 'State parameter is required.'}, status=422)
        deleted = Pincode.objects.filter(state=state).delete()
        return JsonResponse({'success': True, 'deleted': deleted[0]})
    return JsonResponse({'success': False, 'message': 'Method not allowed.'}, status=405)

@admin_login_required
def get_districts(request):
    state = request.GET.get('state')
    districts = list(Pincode.objects.filter(state=state).values_list('district', flat=True).distinct().order_by('district'))
    return JsonResponse({'districts': districts})
