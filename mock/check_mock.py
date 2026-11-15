"""목데이터가 레코드 규칙을 지키는지 검사한다. 표준 라이브러리만 쓴다.

    python mock/check_mock.py

목데이터를 고치거나 늘린 뒤에 돌린다. 백엔드가 같은 규칙을 지키는지 볼 때도 참고한다.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
STATUSES = {"fetched", "parsed", "extracted", "failed"}
ROLES = {"Background", "Contribution", "Method", "Setup", "Result",
         "Analysis", "Limitation", "Caption", "Other"}
STRENGTHS = {"sota", "outperforms", "partial", "comparable", "none"}
CONDITION_KEYS = {"datasets", "baselines", "metrics", "runs", "resources", "limitations"}
CLAIM_KEYS = {"claim_id", "paper_id", "claim_sentence", "evidence", "conditions",
              "hedge", "strength", "confidence", "checks"}
MAX_CLAIMS = 5

errors = []


def err(msg):
    errors.append(msg)


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


papers = load("papers.json")
sentences = load("sentences.json")
claims = load("claims.json")

paper_by_id = {}
for p in papers:
    pid = p["paper_id"]
    if pid in paper_by_id:
        err(f"paper 중복: {pid}")
    paper_by_id[pid] = p
    if p["status"] not in STATUSES:
        err(f"{pid}: status 값이 이상함 ({p['status']})")
    if (p["status"] == "failed") != (p["error"] is not None):
        err(f"{pid}: failed일 때만 error가 있어야 함")
    if "v" in pid.split(":")[-1]:
        err(f"{pid}: paper_id에 버전이 들어 있음")

# 문장: 논문마다 0부터 빈틈없이
idx_by_paper = {}
for s in sentences:
    pid = s["paper_id"]
    if pid not in paper_by_id:
        err(f"sentence가 없는 논문을 가리킴: {pid}")
        continue
    idx_by_paper.setdefault(pid, []).append(s["idx"])
    if s["role"] not in ROLES:
        err(f"{pid}#{s['idx']}: role 값이 이상함 ({s['role']})")
for pid, idxs in idx_by_paper.items():
    if sorted(idxs) != list(range(len(idxs))):
        err(f"{pid}: 문장 번호가 0부터 이어지지 않음")
    if paper_by_id[pid]["status"] in {"fetched", "failed"}:
        err(f"{pid}: {paper_by_id[pid]['status']} 논문에 문장이 있음")

# 주장: 번호만, 범위 안, extracted 논문에만
count = {}
for c in claims:
    pid = c["paper_id"]
    if set(c) != CLAIM_KEYS:
        err(f"{c.get('claim_id')}: 칸이 다름 {sorted(set(c) ^ CLAIM_KEYS)}")
    if pid not in paper_by_id:
        err(f"claim이 없는 논문을 가리킴: {pid}")
        continue
    if paper_by_id[pid]["status"] != "extracted":
        err(f"{c['claim_id']}: extracted가 아닌 논문에 claim이 있음")
    if c["claim_id"] != f"{pid}#{c['claim_sentence']}":
        err(f"{c['claim_id']}: claim_id가 '{{paper_id}}#{{주장문장번호}}' 형식이 아님")
    if c["strength"] not in STRENGTHS:
        err(f"{c['claim_id']}: strength 값이 이상함")
    if set(c["conditions"]) != CONDITION_KEYS:
        err(f"{c['claim_id']}: conditions 칸이 다름")
    nums = [c["claim_sentence"], *c["evidence"], *c["hedge"],
            *(n for v in c["conditions"].values() for n in v)]
    n_sent = len(idx_by_paper.get(pid, []))
    for n in nums:
        if not isinstance(n, int) or isinstance(n, bool):
            err(f"{c['claim_id']}: 번호가 아닌 값이 있음 ({n!r}) — claim에는 텍스트를 넣지 않는다")
        elif not 0 <= n < n_sent:
            err(f"{c['claim_id']}: 범위(0~{n_sent - 1}) 밖의 문장 번호 {n}")
    count[pid] = count.get(pid, 0) + 1
for pid, n in count.items():
    if n > MAX_CLAIMS:
        err(f"{pid}: claim이 {n}개 (최대 {MAX_CLAIMS})")

if errors:
    print("문제 있음:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print(f"통과: paper {len(papers)}개, sentence {len(sentences)}개, claim {len(claims)}개")
