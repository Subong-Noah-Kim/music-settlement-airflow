from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime
from utils.music_logic import download_files_from_drive, process_music_settlement, style_google_sheet

# [보안 수정] 환경변수 사용을 위해 os 모듈 임포트
import os

# --------------------------------------------------------------------------
# [설정] 비밀 정보는 이제 코드에 남기지 않고 환경변수(.env)에서 가져옵니다.
# --------------------------------------------------------------------------
# 만약 .env 값을 못 읽으면 None이 되므로, 안전장치를 위해 getenv 사용
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
SPREADSHEET_ID  = os.getenv("GOOGLE_SPREADSHEET_ID")
KEY_FILE_NAME   = os.getenv("GOOGLE_KEY_FILE_NAME", "service_account.json")

# Docker 내부 경로는 고정되어 있으므로 그대로 둡니다.
DATA_DIR        = "/opt/airflow/data"
KEY_PATH        = f"/opt/airflow/keys/{KEY_FILE_NAME}"
SCOPE           = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

# (혹시 환경변수가 안 읽혔을 때 에러를 빨리 뱉도록 검증 로직 추가)
if not DRIVE_FOLDER_ID or not SPREADSHEET_ID:
    raise ValueError("❌ .env 파일에서 Google ID 정보를 찾을 수 없습니다! docker-compose를 확인하세요.")

default_args = {
    'owner': 'subong',
    'start_date': datetime(2025, 1, 1),
    'retries': 0,
}

with DAG('music_settlement_final', 
         default_args=default_args, 
         schedule_interval='@monthly', 
         catchup=False) as dag:

    # 1. 다운로드 태스크
    t1 = PythonOperator(
        task_id='download',
        python_callable=download_files_from_drive,
        # [중요] 함수의 인자(파라미터)를 여기서 넘겨줍니다.
        op_kwargs={
            'drive_folder_id': DRIVE_FOLDER_ID,
            'key_path': KEY_PATH,
            'data_dir': DATA_DIR,
            'scope': SCOPE
        }
    )

    # 2. 처리 및 업로드 태스크
    t2 = PythonOperator(
        task_id='process',
        python_callable=process_music_settlement,
        op_kwargs={
            'data_dir': DATA_DIR,
            'key_path': KEY_PATH,
            'spreadsheet_id': SPREADSHEET_ID,
            'scope': SCOPE
        }
    )

    # 3. 디자인 적용 태스크
    t3 = PythonOperator(
        task_id='style',
        python_callable=style_google_sheet,
        op_kwargs={
            'key_path': KEY_PATH,
            'spreadsheet_id': SPREADSHEET_ID,
            'scope': SCOPE
        }
    )

    # 순서 연결
    t1 >> t2 >> t3