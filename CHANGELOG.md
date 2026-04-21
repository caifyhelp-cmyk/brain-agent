# brain-agent 변경 이력

---

## 2026-04-21 (세션 2 — 버그픽스 집중)

### 버그 수정
- **SQLite 데이터 소실 문제 해결** (`db.py`)
  - PostgreSQL 연결 실패 시 `_USE_PG = False`로 영구 전환 → SQLite에 저장 → 배포 때 전부 소실
  - 수정: PostgreSQL 환경에서는 폴백 없음. 연결 실패는 에러로 표면화
  - 로컬 개발(DATABASE_URL 미설정)만 SQLite 유지

- **`thinking={'type': 'adaptive'}` 전체 제거** (`agent.py`, `video_simulator.py`, `simulate_shorts.py`)
  - `adaptive`는 존재하지 않는 Claude API 값 → 즉시 에러
  - 우선 thinking 자체를 제거 (Gunicorn 타임아웃 방지)

- **Gunicorn timeout 120초 → 300초** (`render.yaml`)
  - 영상 시뮬 전체 파이프라인(GPT×2 + Claude×2) 처리 시간 초과 방지

- **`_get_relevant_patterns()` 반환 튜플 미처리** (`app.py` 블로그 생성 경로)
  - `patterns_str = _get_relevant_patterns(situation)` → `patterns_str, _ = ...`

- **이중 중괄호 버그** (`agent.py`)
  - `{{category}}` → `{category}`, `{{'key': val}}` → `{'key': val}`
  - 케이스스터디 패턴 필터 키워드 수정: `'메에스트로'` → `'미흡'`

- **`/api/research` patterns 필드 추가** (`app.py`)
  - 형식: `[{category, rules:[...]}]` 카테고리별 최대 8개 원칙
  - MAESTRO에서 `_fmt_patterns()`로 파싱

- **Flask 글로벌 에러 핸들러 추가** (`app.py`)
  - 500 에러를 HTML 대신 JSON으로 반환해 디버깅 용이

### 환경 설정
- Render `ANTHROPIC_API_KEY` 추가 (기존 미설정 → 영상 시뮬 401 에러)
- Anthropic API 키 갱신 (구 키 만료 확인)

---

## 2026-04-21 (세션 1 — 패턴 고도화)

### 변경
- `agent.py`: `_get_relevant_patterns()` 반환 타입 `str` → `(str, list)` 튜플
  - 케이스스터디형 패턴 필터링 (`미흡/부재/실패로/과소평가` 제외)
  - `matched_patterns` 리스트를 `analyze()` 결과에 포함
- `app.py`: `/api/research` 응답에 `patterns` 필드 추가

---

## 이전 히스토리
- `git log` 참조
