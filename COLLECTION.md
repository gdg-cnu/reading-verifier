# arXiv 수집기 (초기 구현)

## 범위와 가정
- 시작: 2026-11-11 00:00 Asia/Seoul (UTC 2026-11-10 15:00). API 결과의 최초 공개 시각으로 필터링한다.
- 분야: 팀의 CS/AI 세부 범위가 미확정이므로 `cs.AI`를 임시 기본값으로 사용한다. `ARXIV_CATEGORY`로 단일 카테고리를 바꿀 수 있다. 설정 변경 시 기존 DB가 유지된다.
- 신규 논문만: arXiv ID당 최초 발견된 버전 한 개를 저장한다. API가 처음부터 v2 이상을 반환하면 그 버전을 사용한다. 이미 등록된 ID의 새 버전은 저장·다운로드하지 않는다. 팀 결정 전 임시 정책이다.
- API는 메타데이터, 별도 HTML URL은 원본을 제공한다. HTML 404는 미제공 후보로 기록하며, 그 외 오류는 실패로 기록한다. HTML 구조 품질은 아직 평가하지 않는다.
- 파싱, 추출, 화면, 스케줄러 설치는 이 모듈 범위 밖이다.

## 준비
Python 3.10 이상과 로컬 MySQL이 필요하다. 빈 DB를 먼저 만들고 스키마를 적용한다. 아래 명령은 저장소 루트에서 실행한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mysql -u YOUR_USER -p -e 'CREATE DATABASE reading_verifier CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;'
mysql -u YOUR_USER -p reading_verifier < schema.sql
export MYSQL_USER=YOUR_USER
export MYSQL_DATABASE=reading_verifier
export MYSQL_PASSWORD='YOUR_PASSWORD'
python -m collector.main
```

비밀번호를 저장소에 넣거나 실제 비밀번호가 든 명령을 공유하지 않는다. `MYSQL_HOST` (기본 127.0.0.1), `MYSQL_PORT` (3306), `RAW_DATA_DIR` (data/raw), `ARXIV_CATEGORY` (cs.AI)는 선택 설정이다. DB DATETIME 값은 UTC다. 원본 파일과 MySQL을 함께 백업해야 한다.

## 실행과 재개
프로그램은 시작일 이후를 UTC 1일 구간으로 매번 다시 조회하고 ID 중복을 제거한다. 데이터가 커지면 요청이 늘어나므로 추후 겹침 구간과 정기 전체 대조를 갖춘 체크포인트로 개선한다. API 요청은 연속 요청 사이 최소 3초, 단일 프로세스다. 등록과 작업 생성은 한 트랜잭션으로 저장하며 MySQL 잠금으로 동시 실행을 막는다. 중단된 다운로드는 다음 실행에 다시 시도하고 원본 파일은 SHA-256 비교 후 재사용한다. 원본과 DB는 별도 저장소이므로 재시작 시 파일을 재검증해 복구한다. 재시도 실패는 다음 실행에서도 처리한다. 404는 자동 재시도하지 않으며 확인 후 작업 상태를 수동으로 pending으로 변경할 수 있다.

HTML 파일 하나만 저장하며 이미지 등 외부 자산과 구조 품질은 아직 보장하지 않는다. URL, 크기, 해시 및 상대 경로는 `paper_files`에 저장한다. 파싱에는 `arxiv_id`, `version`, `storage_path`를 전달하고, 별도 컴퓨터라면 파일도 전달한다.

매일 09:00 KST 실행은 운영 환경에서 별도 스케줄러를 설정해야 한다. 예: macOS에서는 launchd의 StartCalendarInterval을 사용하고, 프로그램 절대 경로와 환경변수, 로그 경로를 설정한다. 컴퓨터가 꺼져 있거나 잠자기 중인 동안 실행을 보장하지 않으므로 다음 수동/예약 실행 시 백필한다. 이 저장소는 스케줄을 자동 설치하지 않는다.

## 검증
```bash
python -m unittest discover -s tests -v
```
실제 MySQL과 arXiv 연결은 별도 환경에서 확인해야 한다.

## 데이터 검증
```bash
python -m collector.verify
```
저장 논문 수와 고유 ID 수, 작업 상태별 건수, 원본 파일의 존재·크기·SHA-256을 읽기 전용으로 확인한다. 무결성 오류가 있으면 종료 코드 1을 반환한다. 파싱의 정확성이나 API에서 논문이 누락되지 않았는지는 이 검사만으로 보장되지 않는다.

## 매일 예약 실행
`scripts/run_scheduled.sh`는 macOS 로그인 키체인의 `reading-verifier-mysql` 서비스에서 MySQL 비밀번호를 읽고 `.venv`를 사용해 실행한다. 비밀번호를 소스·plist·로그에 기록하지 않는다. 키체인이 잠겼거나 접근 승인이 필요한 경우 실행이 실패할 수 있다. 예약 시각은 macOS 현지 시간 오전 9시이며 한국 시간으로 실행하려면 시스템 시간대를 Asia/Seoul로 유지한다. 컴퓨터가 꺼진 동안의 실행은 누락될 수 있다. 다음 실행은 시작일부터 논문 목록을 다시 조회하여 중복을 제거한다. 임시 작업 파일이 아닌 프로젝트 `.venv`가 필요하다.

예약 설정 plist는 실행 사용자와 저장소의 절대 경로를 포함하므로 Git에 포함하지 않는다. 각 개발자는 로컬 환경에 맞게 launchd 설정을 생성해야 한다.
