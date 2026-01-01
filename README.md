# 🎵 Music Settlement Automation Pipeline

매월 수작업으로 진행하던 **음원 정산 데이터 집계 및 리포팅 업무를 자동화**한 Airflow 파이프라인 프로젝트입니다.
구글 드라이브에 업로드된 엑셀 파일을 감지하여 데이터를 가공하고, 구글 스프레드시트에 시각화된 리포트를 자동으로 생성합니다.

---

## 🚀 Key Features (주요 기능)

1.  **자동 변경 감지 (Polling Sensor)**
    * 결국 구현하지 않음

2.  **데이터 자동 집계 (Data Processing)**
    * 여러 개의 엑셀 파일(월별/건별)을 자동으로 병합합니다.
    * **앨범별 수익**과 **플랫폼(서비스)별 수익**을 각각 피벗(Pivot)하여 다각도로 분석합니다.
    * 플랫폼별 데이터는 **매출액 순(내림차순)**으로 자동 정렬되어 중요도를 즉시 파악할 수 있습니다.

3.  **스마트 리포팅 (Smart Reporting & Styling)**
    * `gspread`를 활용해 구글 스프레드시트에 데이터를 업로드합니다.
    * **조건부 서식 자동화:** 헤더(회색), 합계 행(진한 회색), 숫자 포맷(천 단위 콤마)을 자동으로 적용합니다.
    * **한글 맞춤형 열 너비:** 데이터 길이를 계산하여 열 너비를 자동으로 최적화합니다.

4.  **보안 및 안정성 (Security)**
    * 민감한 API Key와 ID는 `.env` 환경변수로 관리하여 코드 노출을 방지합니다.
    * Docker 환경에서 구동되어 OS에 상관없이 일관된 실행 환경을 보장합니다.

---

## 🛠 Architecture

```mermaid
graph LR
    A[Google Drive\n(Excel Files)] -->|Polling (30min)| B(Airflow Sensor)
    B -->|New Files Detected?| C{Trigger Pipeline}
    C -->|Yes| D[Download Task]
    D --> E[Data Processing\n(Pandas Pivot/Merge)]
    E --> F[Styling & Upload\n(Gspread API)]
    F --> G[Google Sheets\n(Final Report)]

```

---

## 📂 Directory Structure

```bash
music-settlement-airflow/
├── dags/
│   ├── settlement_job.py      # DAG 정의 (스케줄링 및 태스크 연결)
│   └── utils/
│       └── music_logic.py     # 핵심 로직 (구글 연동, 데이터 전처리, 스타일링)
├── keys/                      # 서비스 계정 키 (gitignore 처리됨)
├── data/                      # 엑셀 파일 임시 저장소 (gitignore 처리됨)
├── logs/                      # Airflow 로그
├── docker-compose.yml         # Docker 환경 설정
├── .env                       # 환경 변수 (gitignore 처리됨)
├── .gitignore                 # 보안 설정
└── requirements.txt           # (Optional) 의존성 목록

```

---

## 🔧 Installation & Setup

이 프로젝트를 실행하기 위해서는 **Docker**와 **Google Cloud Service Account**가 필요합니다.

### 1. Clone Repository

```bash
git clone [https://github.com/Subong-Noah-Kim/music-settlement-airflow.git](https://github.com/Subong-Noah-Kim/music-settlement-airflow.git)
cd music-settlement-airflow

```

### 2. Google Credentials Setup

1. Google Cloud Console에서 **Service Account(서비스 계정)**를 생성하고 JSON 키를 다운로드합니다.
2. `keys/` 폴더를 생성하고 JSON 파일을 위치시킵니다. (예: `keys/service_account.json`)
3. 구글 드라이브 폴더와 결과 시트에 해당 서비스 계정 이메일(`xxx@xxx.iam.gserviceaccount.com`)을 **[편집자]** 권한으로 공유합니다.

### 3. Environment Variables (.env)

프로젝트 루트에 `.env` 파일을 생성하고 아래 정보를 입력합니다.

```ini
# .env file example
GOOGLE_DRIVE_FOLDER_ID=your_drive_folder_id_here
GOOGLE_SPREADSHEET_ID=your_spreadsheet_id_here
GOOGLE_KEY_FILE_NAME=service_account.json

```

### 4. Run with Docker

```bash
docker-compose up -d

```

* Airflow Webserver: `http://localhost:8080`
* 초기 계정: `admin` / `admin` (설정 파일 참조)

---

## 📊 Logic Detail

### Data Transformation

* **Column Cleansing:** 파일마다 상이할 수 있는 컬럼명("곡명" vs "앨범명")을 통일하고 공백을 제거합니다.
* **Deduplication:** 중복된 컬럼이나 데이터를 제거하여 집계 오류를 방지합니다.
* **Structure:**
1. **Album View:** 기준년월 x 앨범명
2. **Platform View:** 기준년월 x 서비스명 (매출 상위 순 정렬)



### Smart Styling

* **Header Detection:** `[참고]` 키워드 등을 인식하여 중간 헤더에도 스타일을 적용합니다.
* **Total Row:** `총계` 행을 자동으로 찾아 강조 표시(Bold + Background)합니다.

---

## 📝 License

This project is for personal portfolio and internal use.

```

---
