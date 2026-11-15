# 백엔드 작업 안내 (스프린트 1)

다른 모듈이 아직 없어도 백엔드를 혼자 끝까지 만들어 볼 수 있도록, 파이프라인에서 백엔드의 자리와 목데이터를 정리했습니다.

## 1. 전체 흐름에서 백엔드의 자리

```
수집 ──▶ paper ──▶ 파싱 ──▶ sentence[] ──▶ 추출 ──▶ claim
                                                       │
                              저장소(로컬 DB) ◀─────────┘
                                   │
                              백엔드(REST API) ──▶ 화면
```

- 앞 모듈(수집·파싱·추출)이 레코드 세 종류(`paper`, `sentence`, `claim`)를 만들어 저장합니다.
- **백엔드는 저장된 레코드를 읽어 API로 내보냅니다.** 스프린트 1에서는 읽기만 합니다.
- 앞 모듈이 아직 없으므로 `mock/` 폴더의 JSON을 DB에 넣어서 시작합니다. 나중에는 앞 모듈이 같은 형태로 DB를 채웁니다.

## 2. 목데이터 (`mock/`)

| 파일 | 내용 |
| --- | --- |
| `papers.json` | 논문 4편 |
| `sentences.json` | 문장 34개 |
| `claims.json` | 주장 3개 |
| `check_mock.py` | 목데이터가 레코드 규칙을 지키는지 검사 (`python mock/check_mock.py`) |

목데이터는 **지어낸 논문**입니다. 제목에 `[MOCK]`을 붙였고, 실제 arXiv에 없는 번호(`9901.xxxxx`)를 썼습니다.

논문 4편은 상태가 모두 다릅니다. 화면이 상태마다 다르게 보여야 하므로 API도 넷을 구분해 줘야 합니다.

| paper_id | status | 문장 | 주장 | 확인할 것 |
| --- | --- | --- | --- | --- |
| `arxiv:9901.00001` | `extracted` | 23 | 3 | 정상 경로 |
| `arxiv:9901.00002` | `extracted` | 6 | 0 | **주장이 없는 논문** (추출은 했음) |
| `arxiv:9901.00003` | `parsed` | 5 | 0 | **아직 추출 안 함** |
| `arxiv:9901.00004` | `failed` | 0 | 0 | 수집 실패, `error`에 이유 |

`9901.00002`와 `9901.00003`은 둘 다 주장이 0개지만 뜻이 다릅니다. "시도했는데 없었다"와 "아직 안 했다"를 구분하는 것이 이 프로젝트의 규칙입니다.

## 3. 레코드 세 종류

칸의 뜻은 목데이터를 보면 대부분 알 수 있습니다. 백엔드가 알아야 할 것만 적습니다.

**paper**
- `paper_id`는 버전을 뺀 번호입니다(`arxiv:9901.00001`). 받은 버전은 `version`에 따로 있습니다.
- `fulltext_path`는 전문 파일 경로입니다. **전문은 DB에 넣지 않습니다.** API로도 내보내지 않습니다.
- `status`: `fetched` → `parsed` → `extracted` 순서로 진행합니다. 중간에 실패하면 `failed`가 됩니다.

**sentence**
- `(paper_id, idx)`가 한 문장을 가리킵니다. `idx`는 논문 안에서 0부터 매긴 번호입니다.
- **번호를 다시 매기거나 비우지 않습니다.** claim이 이 번호로 문장을 가리킵니다.
- `role` 값: `Background` `Contribution` `Method` `Setup` `Result` `Analysis` `Limitation` `Caption` `Other`

**claim**
- `claim_id`는 `{paper_id}#{주장 문장 번호}`입니다.
- `claim_sentence`, `evidence`, `hedge`, `conditions` 안의 값은 **모두 문장 번호**입니다.
- **claim에는 텍스트를 한 글자도 넣지 않습니다.** 저장할 때도, 응답할 때도 마찬가지입니다. 모델이 만든 문장이 사용자에게 가는 길을 막기 위한 규칙입니다. 문장 내용은 화면이 `sentence`에서 번호로 찾아 씁니다.
- `conditions`는 스프린트 2부터 채웁니다. 목데이터에는 형태를 보여 주려고 채워 두었습니다. 비어 있어도 응답이 깨지지 않게 해 주세요.

리스트 값(`authors`, `evidence` 등)을 DB에 어떻게 저장할지(JSON 칸, 별도 테이블)는 자유롭게 정하면 됩니다.

## 4. 만들 API

### `GET /papers`
논문 목록입니다. 쿼리로 거를 수 있습니다.

| 쿼리 | 예 | 뜻 |
| --- | --- | --- |
| `category` | `cs.CL` | 이 카테고리가 들어간 논문 |
| `from`, `to` | `2026-10-01` | `published_at` 범위 (둘 다 포함) |

```jsonc
// 200
{
  "papers": [
    {
      "paper_id": "arxiv:9901.00001",
      "version": "v2",
      "title": "...",
      "authors": ["..."],
      "abstract": "...",
      "categories": ["cs.CL"],
      "published_at": "2026-10-28",
      "source_url": "...",
      "status": "extracted",
      "error": null
    }
  ]
}
```

### `GET /papers/{paper_id}`
논문 하나와 문장 배열입니다. 문장은 `idx` 순서로 줍니다.

```jsonc
// 200
{
  "paper": { /* 위와 같은 칸 */ },
  "sentences": [
    { "idx": 0, "text": "...", "section": "Abstract", "role": "Contribution", "parser_version": "html-0.1.0-mock" }
  ]
}
// failed 논문은 "sentences": []
// 없는 논문은 404 { "error": "paper_not_found" }
```

### `GET /papers/{paper_id}/claims`
주장 구조입니다. `status`를 함께 줘야 화면이 "주장 없음"과 "아직 안 함"을 구분합니다.

```jsonc
// 200
{
  "paper_id": "arxiv:9901.00001",
  "status": "extracted",
  "claims": [ /* claim 레코드 그대로. 텍스트를 붙이지 않는다 */ ]
}
// 9901.00002 → "status": "extracted", "claims": []
// 9901.00003 → "status": "parsed",    "claims": []
// 없는 논문은 404
```

**`paper_id`의 콜론(`:`)**: 경로에 `arxiv:9901.00001`처럼 그대로 오기도 하고 `arxiv%3A9901.00001`로 인코딩되어 오기도 합니다. 둘 다 받아 주세요.

## 5. 정한 것과 정할 것

- **정한 것**: DB는 로컬 DB(예: SQLite)
- **자유롭게 정할 것**: 언어·프레임워크, 테이블 설계, 폴더 구조
- **나중에 할 것** (스프린트 1 범위 밖)
  - `POST /papers/{id}/extract`: 추출 요청. 바로 `job_id`를 돌려줍니다.
  - `GET /jobs/{job_id}`: 진행 중 · 완료 · 실패
  - 작업 큐는 별도 큐 서비스 없이 **DB 테이블에 작업 상태를 기록하는 방식**으로 시작합니다. 테이블을 설계할 때 염두에 두면 좋습니다.

## 6. 다 됐는지 확인하기

- [ ] `mock/*.json`을 DB에 넣는 스크립트가 있다 (여러 번 돌려도 중복되지 않는다)
- [ ] `GET /papers` → 4편. `?category=cs.CL` → `9901.00001`, `9901.00004`. `?from=2026-11-01` → `9901.00003`, `9901.00004`
- [ ] `GET /papers/arxiv:9901.00001` → 문장 23개, `idx` 0~22 순서
- [ ] `GET /papers/arxiv:9901.00004` → `status: failed`, `error` 있음, 문장 0개
- [ ] `GET /papers/arxiv:9901.00001/claims` → 주장 3개, 값은 모두 번호
- [ ] `GET /papers/arxiv:9901.00002/claims`와 `.../9901.00003/claims`의 `status`가 다르다
- [ ] 없는 논문 → 404
- [ ] 응답 어디에도 `fulltext_path`가 없다

## 7. 아직 열려 있는 것

아래는 팀에서 정하는 중입니다. 정해지면 이 문서를 고칩니다.

- **레코드 정의 파일**: 코드 파일 한 곳에 레코드를 정의할 예정입니다. 만들어지면 칸 이름은 그 파일이 기준입니다. 레코드 형태를 바꾸고 싶으면 팀에 먼저 공유해 주세요.
- **claim의 파서 버전**: 파서가 바뀌면 번호가 밀리므로, claim이 어느 파서 버전에서 나왔는지 알아야 합니다. 지금 claim 레코드에는 그 칸이 없습니다.
- **목록 페이지 나누기**: 논문이 많아지면 필요합니다. 스프린트 1에서는 없어도 됩니다.

궁금한 점은 경준에게 물어보세요.
