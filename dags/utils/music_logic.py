import pandas as pd
import os
import re
import json
import traceback
import numpy as np
import gspread
import logging
from oauth2client.service_account import ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io

logger = logging.getLogger("airflow.task")

def _get_files_recursive(service, parent_id):
    found_files = []
    page_token = None
    while True:
        query = f"'{parent_id}' in parents and trashed = false"
        response = service.files().list(q=query, fields="nextPageToken, files(id, name, mimeType)", pageToken=page_token).execute()
        items = response.get('files', [])
        for item in items:
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                found_files.extend(_get_files_recursive(service, item['id']))
            elif 'spreadsheet' in item['mimeType'] or item['name'].endswith('.xlsx'):
                found_files.append(item)
        page_token = response.get('nextPageToken')
        if not page_token: break
    return found_files

def download_files_from_drive(drive_folder_id, key_path, data_dir, scope):
    logger.info(f"📥 구글 드라이브 탐색 시작 (Root ID: {drive_folder_id})")
    if not os.path.exists(key_path): raise FileNotFoundError(f"인증 키 없음")
    
    creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
    service = build('drive', 'v3', credentials=creds)
    
    target_files = _get_files_recursive(service, drive_folder_id)
    if not target_files: return

    if not os.path.exists(data_dir): os.makedirs(data_dir)
    for f in os.listdir(data_dir): os.remove(os.path.join(data_dir, f))
    
    for file in target_files:
        safe_name = f"{os.path.splitext(file['name'])[0]}_{file['id'][-6:]}.xlsx"
        try:
            req = service.files().export_media(fileId=file['id'], mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') if file['mimeType'] == 'application/vnd.google-apps.spreadsheet' else service.files().get_media(fileId=file['id'])
            fh = io.FileIO(os.path.join(data_dir, safe_name), 'wb')
            downloader = MediaIoBaseDownload(fh, req)
            done = False
            while not done: _, done = downloader.next_chunk()
        except: pass
    logger.info(f"✅ 다운로드 완료: {len(target_files)}건")

# -----------------------------------------------------------------------------
# [업그레이드] 정렬 옵션(sort_by_col_sum) 추가
# -----------------------------------------------------------------------------
def _finalize_dataframe(df_list, index_name="기준년월", sort_by_col_sum=False):
    if not df_list: return None
    
    # 1. 병합
    final_df = pd.concat(df_list, axis=0, sort=False).fillna(0)
    
    # [NEW] 컬럼 정렬 (총액 기준 내림차순)
    if sort_by_col_sum:
        # 숫자 데이터만 더해서 순위 매기기
        col_sums = final_df.select_dtypes(include=[np.number]).sum()
        sorted_cols = col_sums.sort_values(ascending=False).index.tolist()
        # 정렬된 순서대로 컬럼 재배치
        final_df = final_df[sorted_cols]

    final_df.index.name = index_name
    final_df = final_df.reset_index()
    
    # 2. 가로 합계 (Row Sum)
    num_cols = final_df.select_dtypes(include=['float', 'int']).columns
    final_df['합계'] = final_df[num_cols].sum(axis=1)
    
    # 3. 세로 합계 (Column Sum) 및 정렬
    final_df = final_df.sort_values([index_name], ascending=[True])
    
    sum_series = final_df.select_dtypes(include=[np.number]).sum()
    sum_row = pd.DataFrame(sum_series).T
    sum_row[index_name] = '총계'
    
    final_df = pd.concat([final_df, sum_row], ignore_index=True)
    final_df = final_df.replace({np.nan: '', np.inf: 0, -np.inf: 0})
    
    return final_df

def process_music_settlement(data_dir, key_path, spreadsheet_id, scope):
    logger.info("🚀 데이터 집계 시작 (앨범별 + 플랫폼별 정렬 적용)")
    files = [f for f in os.listdir(data_dir) if f.endswith('.xlsx')]
    if not files: return

    all_album_data = []
    all_platform_data = [] 
    
    for filename in files:
        try:
            date_match = re.search(r'(20\d{4})', filename)
            base_date = date_match.group(1) if date_match else None
            if not base_date: continue

            sheets_dict = pd.read_excel(os.path.join(data_dir, filename), sheet_name=None, header=None)
            target_df = None
            for _, df in sheets_dict.items():
                if len(df) < 2: continue
                if df.astype(str).apply(lambda x: x.str.contains("서비스명")).any().any():
                    target_df = df; break
            
            if target_df is None: continue
            
            start_index = None
            for idx, row in target_df.iterrows():
                if row.astype(str).str.contains("서비스명").any():
                    start_index = idx; break
            
            new_header = target_df.iloc[start_index]
            df = target_df[start_index + 1:].copy()
            df.columns = new_header
            
            df.columns = df.columns.astype(str).str.strip()
            rename_map = {"곡명": "앨범명", "기획사정산금액": "정산금액"}
            df.rename(columns=rename_map, inplace=True)
            df = df.loc[:, ~df.columns.duplicated()]

            if "정산금액" not in df.columns: continue
            
            df["정산금액"] = pd.to_numeric(df["정산금액"].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

            # 1. 앨범별 피벗 (기존대로)
            if "앨범명" in df.columns:
                pivot_album = df.pivot_table(index=[pd.Index([base_date]*len(df), name="기준년월")], columns="앨범명", values="정산금액", aggfunc='sum').fillna(0)
                all_album_data.append(pivot_album)

            # 2. 플랫폼별 피벗
            if "서비스명" in df.columns:
                pivot_platform = df.pivot_table(index=[pd.Index([base_date]*len(df), name="기준년월")], columns="서비스명", values="정산금액", aggfunc='sum').fillna(0)
                all_platform_data.append(pivot_platform)

        except Exception as e:
            logger.error(f"파일 처리 중 에러({filename}): {e}")
            continue

    if not all_album_data:
        logger.warning("데이터가 없습니다.")
        return

    # [적용] 앨범은 정렬 X, 플랫폼은 정렬 O (sort_by_col_sum=True)
    final_album_df = _finalize_dataframe(all_album_data, sort_by_col_sum=False)
    final_platform_df = _finalize_dataframe(all_platform_data, sort_by_col_sum=True)

    # 데이터 조립
    upload_data = [final_album_df.columns.values.tolist()] + final_album_df.values.tolist()
    upload_data.append([]) 
    upload_data.append([]) 
    upload_data.append(["[참고] 플랫폼별 월별 수익 현황"]) 
    
    if final_platform_df is not None:
        upload_data.append(final_platform_df.columns.values.tolist())
        upload_data.extend(final_platform_df.values.tolist())

    # JSON 직렬화 체크
    try: json.dumps(upload_data)
    except TypeError:
        new_upload = []
        for row in upload_data: new_upload.append([str(x) for x in row])
        upload_data = new_upload

    try:
        logger.info(f"☁️ 구글 시트(ID: {spreadsheet_id}) 업로드 중...")
        creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
        client = gspread.authorize(creds)
        sh = client.open_by_key(spreadsheet_id)
        worksheet = sh.get_worksheet(0)
        worksheet.clear()
        sh.values_update(f"'{worksheet.title}'!A1", params={'valueInputOption': 'USER_ENTERED'}, body={'values': upload_data})
        logger.info(f"🎉 업로드 성공!")

    except Exception as e:
        if "<Response [200]>" in str(e): logger.info("🎉 성공 (200 OK)")
        else: logger.error(f"❌ 실패: {e}\n{traceback.format_exc()}")

# -----------------------------------------------------------------------------
# [업그레이드] 디자인 함수: 헤더와 합계 행을 '스스로 찾아서' 적용
# -----------------------------------------------------------------------------
def style_google_sheet(key_path, spreadsheet_id, scope):
    logger.info(f"🎨 스마트 디자인 적용 시작")
    if not os.path.exists(key_path): return

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
        client = gspread.authorize(creds)
        sh = client.open_by_key(spreadsheet_id)
        worksheet = sh.get_worksheet(0)
        all_values = worksheet.get_all_values()
        if not all_values: return
        
        last_row = len(all_values)
        last_col = len(all_values[0])
        
        requests = [
            # 1. 헤더 고정
            {"updateSheetProperties": {"properties": {"sheetId": worksheet.id, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
            # 2. 전체 가운데 정렬
            {"repeatCell": {"range": {"sheetId": worksheet.id, "startRowIndex": 1, "endRowIndex": last_row}, "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}}, "fields": "userEnteredFormat(horizontalAlignment)"}},
            # 3. 숫자(콤마) + 우측 정렬 (B열 이후)
            {"repeatCell": {"range": {"sheetId": worksheet.id, "startRowIndex": 1, "endRowIndex": last_row, "startColumnIndex": 1, "endColumnIndex": last_col}, "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}, "horizontalAlignment": "RIGHT"}}, "fields": "userEnteredFormat(numberFormat,horizontalAlignment)"}},
        ]

        # ---------------------------------------------------------------------
        # [NEW] 똑똑한 행 찾기 로직
        # ---------------------------------------------------------------------
        header_style = {"userEnteredFormat": {"textFormat": {"bold": True}, "horizontalAlignment": "CENTER", "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9}}}
        total_style = {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.85, "green": 0.85, "blue": 0.85}}}

        # 1. 첫 번째 줄(무조건 헤더)
        requests.append({"repeatCell": {"range": {"sheetId": worksheet.id, "startRowIndex": 0, "endRowIndex": 1}, "cell": header_style, "fields": "userEnteredFormat(textFormat,horizontalAlignment,backgroundColor)"}})

        # 2. 내용 보면서 '추가 헤더'와 '총계' 찾기
        for i, row in enumerate(all_values):
            if not row: continue
            
            # (1) 플랫폼별 표 제목 바로 다음 줄 = 헤더
            if row[0].startswith("[참고]"):
                # 제목 줄 바로 다음(i+1)이 헤더임
                header_idx = i + 1
                if header_idx < last_row:
                    requests.append({"repeatCell": {"range": {"sheetId": worksheet.id, "startRowIndex": header_idx, "endRowIndex": header_idx+1}, "cell": header_style, "fields": "userEnteredFormat(textFormat,horizontalAlignment,backgroundColor)"}})
            
            # (2) '총계'로 시작하는 줄 = 합계 행 (회색 강조)
            if row[0] == "총계":
                requests.append({"repeatCell": {"range": {"sheetId": worksheet.id, "startRowIndex": i, "endRowIndex": i+1}, "cell": total_style, "fields": "userEnteredFormat(textFormat,backgroundColor)"}})

        # ---------------------------------------------------------------------

        # 너비 자동 맞춤
        df = pd.DataFrame(all_values)
        for col_idx in range(len(df.columns)):
            max_len = df[col_idx].astype(str).map(len).max()
            pixel_width = max(50, min(int(max_len * 12 + 30), 400))
            requests.append({"updateDimensionProperties": {"range": {"sheetId": worksheet.id, "dimension": "COLUMNS", "startIndex": col_idx, "endIndex": col_idx + 1}, "properties": {"pixelSize": pixel_width}, "fields": "pixelSize"}})

        sh.batch_update({"requests": requests})
        logger.info("✨ 스마트 디자인 적용 완료!")

    except Exception as e: logger.error(f"디자인 실패: {e}")

# -----------------------------------------------------------------------------
# [NEW] 파일 변경 감지 (ShortCircuit용)
# -----------------------------------------------------------------------------
def check_drive_changes(drive_folder_id, key_path, scope, data_dir):
    logger.info("👀 구글 드라이브 변경사항 감지 중...")
    
    # 1. 상태를 저장할 파일 경로 (과거의 파일 목록을 기억하는 수첩)
    history_file = os.path.join(data_dir, "drive_history.json")
    
    # 2. 현재 드라이브 파일 목록 가져오기
    if not os.path.exists(key_path): return False
    creds = ServiceAccountCredentials.from_json_keyfile_name(key_path, scope)
    service = build('drive', 'v3', credentials=creds)
    current_files = _get_files_recursive(service, drive_folder_id)
    
    # 비교를 위해 파일 ID만 추출해서 정렬 (Set이나 List)
    current_ids = sorted([f['id'] for f in current_files])
    
    # 3. 과거 기록 불러오기
    last_ids = []
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                last_ids = json.load(f)
                # JSON 로드 시 리스트가 아닐 경우 대비
                if not isinstance(last_ids, list): last_ids = []
                last_ids = sorted(last_ids)
        except:
            last_ids = []

    # 4. 비교 (현재 목록 vs 과거 목록)
    if current_ids == last_ids:
        logger.info("💤 변경사항 없음. 작업을 건너뜁니다.")
        return False  # 뒤에 오는 태스크들 모두 Skip!
    else:
        logger.info(f"✨ 변경 감지! (파일 수: {len(last_ids)} -> {len(current_ids)})")
        
        # [중요] 변경사항이 확인되었으니, 현재 상태를 수첩에 기록해둡니다.
        # (그래야 다음번 실행 때 또 실행하지 않음)
        with open(history_file, 'w') as f:
            json.dump(current_ids, f)
            
        return True   # 작업 진행시켜!