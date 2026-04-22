# -*- coding: utf-8 -*-
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "thinking_brain.db"
PATTERNS_PATH = BASE_DIR / "brain" / "patterns.json"

# Render가 제공하는 PostgreSQL URL (없으면 로컬 SQLite 사용)
_DATABASE_URL = os.environ.get('DATABASE_URL', '')
if _DATABASE_URL.startswith('postgres://'):
    _DATABASE_URL = _DATABASE_URL.replace('postgres://', 'postgresql://', 1)

_USE_PG = bool(_DATABASE_URL)


# ── 커넥션 & 쿼리 헬퍼 ───────────────────────────────────

def get_conn():
    if _USE_PG:
        # PostgreSQL 환경(Render)에서는 SQLite 폴백 없음
        # — 폴백 시 데이터가 임시 파일에 쌓이다 배포 때 전부 소실되기 때문
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(
            _DATABASE_URL,
            cursor_factory=RealDictCursor,
            connect_timeout=30
        )
        return conn
    # 로컬 개발: SQLite
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ph():
    """SQL 플레이스홀더: PostgreSQL=%s, SQLite=?"""
    return '%s' if _USE_PG else '?'


def _pk_def():
    return 'SERIAL PRIMARY KEY' if _USE_PG else 'INTEGER PRIMARY KEY AUTOINCREMENT'


def _now():
    return 'NOW()' if _USE_PG else "datetime('now', 'localtime')"


def _exec(conn, sql, params=None):
    """일반 실행 (UPDATE/DELETE/CREATE)"""
    if _USE_PG:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        conn.commit()
        return cur
    conn.execute(sql, params or [])
    conn.commit()
    return None


def _insert(conn, sql, params=None):
    """INSERT → 새 row id 반환"""
    if _USE_PG:
        cur = conn.cursor()
        cur.execute(sql + ' RETURNING id', params or [])
        conn.commit()
        row = cur.fetchone()
        return row['id'] if row else None
    cur = conn.execute(sql, params or [])
    conn.commit()
    return cur.lastrowid


def _fetchall(conn, sql, params=None):
    if _USE_PG:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    rows = conn.execute(sql, params or []).fetchall()
    return [dict(r) for r in rows]


def _fetchone(conn, sql, params=None):
    if _USE_PG:
        cur = conn.cursor()
        cur.execute(sql, params or [])
        row = cur.fetchone()
        return dict(row) if row else None
    row = conn.execute(sql, params or []).fetchone()
    return dict(row) if row else None


# ── DB 초기화 ────────────────────────────────────────────

def init_db():
    ph = _ph()
    pk = _pk_def()
    now = _now()

    conn = get_conn()

    tables = [
        f'''CREATE TABLE IF NOT EXISTS simulations (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            scenario_json TEXT NOT NULL,
            response_json TEXT NOT NULL,
            patterns_fired TEXT,
            gaps TEXT,
            confidence REAL,
            flagged INTEGER DEFAULT 0,
            reviewed INTEGER DEFAULT 0
        )''',
        f'''CREATE TABLE IF NOT EXISTS weekly_reports (
            id {pk},
            week_start TEXT NOT NULL UNIQUE,
            generated_at TEXT DEFAULT ({now}),
            report_json TEXT NOT NULL
        )''',
        f'''CREATE TABLE IF NOT EXISTS pattern_changes (
            id {pk},
            changed_at TEXT DEFAULT ({now}),
            action TEXT,
            pattern_id INTEGER,
            description TEXT,
            simulation_id INTEGER
        )''',
        f'''CREATE TABLE IF NOT EXISTS training_sessions (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            scenario_json TEXT NOT NULL,
            user_response TEXT NOT NULL,
            evaluation_json TEXT NOT NULL,
            score REAL
        )''',
        f'''CREATE TABLE IF NOT EXISTS real_case_simulations (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            case_id INTEGER NOT NULL,
            company TEXT,
            scenario_json TEXT NOT NULL,
            agent_judgment_json TEXT NOT NULL,
            actual_outcome_json TEXT NOT NULL,
            comparison_json TEXT NOT NULL,
            match_score REAL,
            aligned INTEGER DEFAULT 0,
            patterns_fired TEXT,
            new_patterns_added TEXT,
            flagged INTEGER DEFAULT 0,
            reviewed INTEGER DEFAULT 0
        )''',
        f'''CREATE TABLE IF NOT EXISTS patterns_db (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            rule TEXT NOT NULL,
            created_at TEXT DEFAULT ({now})
        )''',
        f'''CREATE TABLE IF NOT EXISTS conversations (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            user_name TEXT NOT NULL,
            user_role TEXT DEFAULT 'employee',
            topic TEXT DEFAULT '',
            section TEXT DEFAULT 'marketing',
            status TEXT DEFAULT 'active',
            message_count INTEGER DEFAULT 0
        )''',
        f'''CREATE TABLE IF NOT EXISTS conversation_messages (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            user_name TEXT DEFAULT ''
        )''',
        f'''CREATE TABLE IF NOT EXISTS pattern_requests (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            conversation_id INTEGER NOT NULL,
            proposed_category TEXT NOT NULL,
            proposed_rule TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            context TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            reviewed_at TEXT
        )''',
        f'''CREATE TABLE IF NOT EXISTS grow_candidates (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            conversation_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            rule TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            promoted_pattern_id INTEGER
        )''',
        f'''CREATE TABLE IF NOT EXISTS pattern_embeddings (
            pattern_id INTEGER PRIMARY KEY,
            embedding TEXT NOT NULL,
            model TEXT DEFAULT 'text-embedding-3-small',
            created_at TEXT DEFAULT ({now})
        )''',
        f'''CREATE TABLE IF NOT EXISTS video_cases (
            id {pk},
            industry TEXT NOT NULL,
            boring_direction TEXT NOT NULL,
            plan TEXT NOT NULL,
            source TEXT DEFAULT 'manual',
            status TEXT DEFAULT 'approved',
            created_at TEXT DEFAULT ({now})
        )''',
        f'''CREATE TABLE IF NOT EXISTS video_simulations (
            id {pk},
            created_at TEXT DEFAULT ({now}),
            brand_json TEXT NOT NULL,
            brain_judgment_json TEXT NOT NULL,
            draft TEXT NOT NULL,
            round2 TEXT DEFAULT '',
            final_plan TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )''',
    ]

    for sql in tables:
        _exec(conn, sql)

    # 마이그레이션: round2 컬럼 없으면 추가
    try:
        _exec(conn, "ALTER TABLE video_simulations ADD COLUMN round2 TEXT DEFAULT ''")
    except Exception:
        pass

    conn.close()

    # 패턴 JSON → DB 시드 (patterns_db가 비어있을 때만)
    _seed_patterns_from_json()
    # 영상 기획 케이스 시드 (비어있을 때만)
    seed_video_cases()


def _seed_patterns_from_json():
    """patterns.json → patterns_db 최초 1회 마이그레이션 + 카테고리 동기화"""
    conn = get_conn()
    count_row = _fetchone(conn, 'SELECT COUNT(*) as cnt FROM patterns_db')
    count = count_row['cnt'] if count_row else 0
    conn.close()

    try:
        data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))
        patterns = data.get('patterns', [])
    except Exception:
        return

    if not patterns:
        return

    if count == 0:
        # 최초 시드
        conn = get_conn()
        ph = _ph()
        for p in patterns:
            _exec(conn, f'INSERT INTO patterns_db (id, category, rule) VALUES ({ph}, {ph}, {ph})',
                  [p['id'], p['category'], p['rule']])
        conn.close()
        print(f"[DB] patterns.json → patterns_db 마이그레이션 완료 ({len(patterns)}개)")
    else:
        # 카테고리 변경 동기화 (rule은 DB 우선, category만 JSON 기준으로 갱신)
        conn = get_conn()
        ph = _ph()
        json_map = {p['id']: p['category'] for p in patterns}
        db_rows = _fetchall(conn, 'SELECT id, category FROM patterns_db')
        updated = 0
        for row in db_rows:
            new_cat = json_map.get(row['id'])
            if new_cat and new_cat != row['category']:
                _exec(conn, f'UPDATE patterns_db SET category={ph} WHERE id={ph}',
                      [new_cat, row['id']])
                updated += 1
        conn.close()
        if updated:
            print(f"[DB] 카테고리 동기화 완료 ({updated}개 업데이트)")


# ── 패턴 CRUD ────────────────────────────────────────────

def get_patterns():
    """패턴 전체 반환 (DB 우선, fallback: JSON)"""
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT id, category, rule FROM patterns_db ORDER BY id ASC')
    conn.close()

    if rows:
        try:
            data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))
            axes = data.get('axes', [])
        except Exception:
            axes = []
        return {'patterns': rows, 'axes': axes, 'updated_at': date.today().isoformat()}

    # fallback: JSON
    try:
        return json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'patterns': [], 'axes': [], 'updated_at': ''}


def add_pattern(category: str, rule: str, simulation_id=None) -> int:
    conn = get_conn()
    ph = _ph()

    # 새 ID 결정
    row = _fetchone(conn, 'SELECT MAX(id) as mx FROM patterns_db')
    new_id = (row['mx'] or 0) + 1

    _exec(conn, f'INSERT INTO patterns_db (id, category, rule) VALUES ({ph}, {ph}, {ph})',
          [new_id, category, rule])
    _exec(conn,
          f'INSERT INTO pattern_changes (action, pattern_id, description, simulation_id) VALUES ({ph},{ph},{ph},{ph})',
          ['add', new_id, rule, simulation_id])
    conn.close()
    return new_id


def edit_pattern(pattern_id: int, new_rule: str):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f'UPDATE patterns_db SET rule={ph} WHERE id={ph}', [new_rule, pattern_id])
    _exec(conn, f'INSERT INTO pattern_changes (action, pattern_id, description) VALUES ({ph},{ph},{ph})',
          ['edit', pattern_id, new_rule])
    conn.close()


def delete_pattern(pattern_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f'DELETE FROM patterns_db WHERE id={ph}', [pattern_id])
    _exec(conn, f'INSERT INTO pattern_changes (action, pattern_id) VALUES ({ph},{ph})',
          ['delete', pattern_id])
    conn.close()


# ── 시뮬레이션 ───────────────────────────────────────────

def save_simulation(scenario, response, patterns_fired, gaps, confidence, flagged):
    conn = get_conn()
    ph = _ph()
    _insert(conn,
            f'INSERT INTO simulations (scenario_json, response_json, patterns_fired, gaps, confidence, flagged) VALUES ({ph},{ph},{ph},{ph},{ph},{ph})',
            [json.dumps(scenario, ensure_ascii=False),
             json.dumps(response, ensure_ascii=False),
             json.dumps(patterns_fired),
             json.dumps(gaps, ensure_ascii=False),
             confidence,
             1 if flagged else 0])
    conn.close()


def _parse_sim_row(d):
    d['scenario'] = json.loads(d['scenario_json'])
    d['response'] = json.loads(d['response_json'])
    d['patterns_fired'] = json.loads(d.get('patterns_fired') or '[]')
    d['gaps'] = json.loads(d.get('gaps') or '[]')
    return d


def get_recent_simulations(limit=10):
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT * FROM simulations ORDER BY created_at DESC LIMIT {ph}', [limit])
    conn.close()
    return [_parse_sim_row(r) for r in rows]


def get_flagged_simulations():
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT * FROM simulations WHERE flagged=1 AND reviewed=0 ORDER BY created_at DESC')
    conn.close()
    return [_parse_sim_row(r) for r in rows]


def dismiss_simulation(sim_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f'UPDATE simulations SET reviewed=1 WHERE id={ph}', [sim_id])
    conn.close()


def get_dashboard_stats():
    conn = get_conn()
    ph = _ph()
    total = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM simulations') or {}).get('cnt', 0)
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    this_week = (_fetchone(conn, f'SELECT COUNT(*) as cnt FROM simulations WHERE created_at >= {ph}',
                           [week_start]) or {}).get('cnt', 0)
    avg_conf = (_fetchone(conn, 'SELECT AVG(confidence) as avg FROM simulations') or {}).get('avg', 0) or 0
    flagged = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM simulations WHERE flagged=1 AND reviewed=0') or {}).get('cnt', 0)
    pat_count = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM patterns_db') or {}).get('cnt', 0)
    conn.close()
    return {
        'total_simulations': total,
        'this_week': this_week,
        'avg_confidence': round(avg_conf, 1),
        'flagged_pending': flagged,
        'total_patterns': pat_count
    }


def get_pattern_frequency(limit=5):
    conn = get_conn()
    ph = _ph()
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    rows = _fetchall(conn, f'SELECT patterns_fired FROM simulations WHERE created_at >= {ph}', [week_start])
    conn.close()

    freq = {}
    for row in rows:
        for pid in json.loads(row.get('patterns_fired') or '[]'):
            freq[pid] = freq.get(pid, 0) + 1

    patterns_data = get_patterns()
    pattern_map = {p['id']: p for p in patterns_data['patterns']}

    result = []
    for pid, count in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]:
        if pid in pattern_map:
            result.append({'pattern': pattern_map[pid], 'count': count})
    return result


def get_simulations_for_week(week_start):
    conn = get_conn()
    ph = _ph()
    week_end = (datetime.strptime(week_start, '%Y-%m-%d') + timedelta(days=7)).strftime('%Y-%m-%d')
    rows = _fetchall(conn, f'SELECT * FROM simulations WHERE created_at >= {ph} AND created_at < {ph}',
                     [week_start, week_end])
    conn.close()
    return [_parse_sim_row(r) for r in rows]


def get_recurring_gaps(limit=10):
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT gaps FROM simulations ORDER BY created_at DESC LIMIT 30')
    conn.close()
    freq = {}
    for row in rows:
        for g in json.loads(row.get('gaps') or '[]'):
            freq[g] = freq.get(g, 0) + 1
    return [g for g, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]]


def get_pattern_fire_counts(limit=30):
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT patterns_fired FROM simulations ORDER BY created_at DESC LIMIT {ph}', [limit])
    conn.close()
    freq = {}
    for row in rows:
        for pid in json.loads(row.get('patterns_fired') or '[]'):
            freq[pid] = freq.get(pid, 0) + 1
    return freq


# ── 주간 리포트 ──────────────────────────────────────────

def save_weekly_report(week_start, report_data):
    conn = get_conn()
    ph = _ph()
    _exec(conn,
          f'INSERT INTO weekly_reports (week_start, report_json) VALUES ({ph},{ph}) ON CONFLICT (week_start) DO UPDATE SET report_json=EXCLUDED.report_json'
          if _USE_PG else
          f'INSERT OR REPLACE INTO weekly_reports (week_start, report_json) VALUES ({ph},{ph})',
          [week_start, json.dumps(report_data, ensure_ascii=False)])
    conn.close()


def get_weekly_reports(limit=10):
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT * FROM weekly_reports ORDER BY week_start DESC LIMIT {ph}', [limit])
    conn.close()
    result = []
    for row in rows:
        row['report'] = json.loads(row['report_json'])
        result.append(row)
    return result


# ── 트레이닝 ─────────────────────────────────────────────

def save_training_session(scenario, user_response, evaluation):
    conn = get_conn()
    ph = _ph()
    _insert(conn,
            f'INSERT INTO training_sessions (scenario_json, user_response, evaluation_json, score) VALUES ({ph},{ph},{ph},{ph})',
            [json.dumps(scenario, ensure_ascii=False), user_response,
             json.dumps(evaluation, ensure_ascii=False), evaluation.get('overall_score', 0)])
    conn.close()


def get_recent_training_sessions(limit=10):
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT * FROM training_sessions ORDER BY created_at DESC LIMIT {ph}', [limit])
    conn.close()
    for row in rows:
        row['scenario'] = json.loads(row['scenario_json'])
        row['evaluation'] = json.loads(row['evaluation_json'])
    return rows


def save_ask_session(scenario, result, rating=None):
    conn = get_conn()
    ph = _ph()
    _insert(conn,
            f'INSERT INTO training_sessions (scenario_json, user_response, evaluation_json, score) VALUES ({ph},{ph},{ph},{ph})',
            [json.dumps(scenario, ensure_ascii=False), '(라이브 판단 요청)',
             json.dumps(result, ensure_ascii=False), result.get('confidence', 0)])
    conn.close()


# ── 실제 케이스 시뮬레이션 ───────────────────────────────

def save_real_case_simulation(case_id, company, scenario, agent_judgment, actual_outcome, comparison,
                               match_score, aligned, patterns_fired, new_patterns_added, flagged):
    conn = get_conn()
    ph = _ph()
    _insert(conn,
            f'''INSERT INTO real_case_simulations
               (case_id, company, scenario_json, agent_judgment_json, actual_outcome_json, comparison_json,
                match_score, aligned, patterns_fired, new_patterns_added, flagged)
               VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})''',
            [case_id, company,
             json.dumps(scenario, ensure_ascii=False),
             json.dumps(agent_judgment, ensure_ascii=False),
             json.dumps(actual_outcome, ensure_ascii=False),
             json.dumps(comparison, ensure_ascii=False),
             match_score, 1 if aligned else 0,
             json.dumps(patterns_fired), json.dumps(new_patterns_added),
             1 if flagged else 0])
    conn.close()


def get_run_real_case_ids():
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT DISTINCT case_id FROM real_case_simulations')
    conn.close()
    return {row['case_id'] for row in rows}


def _parse_real_row(d):
    d['scenario'] = json.loads(d['scenario_json'])
    d['agent_judgment'] = json.loads(d['agent_judgment_json'])
    d['actual_outcome'] = json.loads(d['actual_outcome_json'])
    d['comparison'] = json.loads(d['comparison_json'])
    d['patterns_fired'] = json.loads(d.get('patterns_fired') or '[]')
    d['new_patterns_added'] = json.loads(d.get('new_patterns_added') or '[]')
    return d


def get_recent_real_case_simulations(limit=10):
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT * FROM real_case_simulations ORDER BY created_at DESC LIMIT {ph}', [limit])
    conn.close()
    return [_parse_real_row(r) for r in rows]


def get_flagged_real_case_simulations():
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT * FROM real_case_simulations WHERE flagged=1 AND reviewed=0 ORDER BY created_at DESC')
    conn.close()
    return [_parse_real_row(r) for r in rows]


def dismiss_real_case(sim_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f'UPDATE real_case_simulations SET reviewed=1 WHERE id={ph}', [sim_id])
    conn.close()


def get_real_case_stats():
    conn = get_conn()
    total = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM real_case_simulations') or {}).get('cnt', 0)
    avg_match = (_fetchone(conn, 'SELECT AVG(match_score) as avg FROM real_case_simulations') or {}).get('avg', 0) or 0
    aligned = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM real_case_simulations WHERE aligned=1') or {}).get('cnt', 0)
    flagged = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM real_case_simulations WHERE flagged=1 AND reviewed=0') or {}).get('cnt', 0)
    conn.close()
    return {'total': total, 'avg_match': round(avg_match, 1), 'aligned': aligned, 'flagged_pending': flagged}


# ── 성장 방 (grow_candidates) ─────────────────────────────

def save_grow_candidates(conv_id: int, candidates: list) -> list:
    """grow 대화에서 추출한 패턴 후보 저장 (별개 방)"""
    conn = get_conn()
    ph = _ph()
    ids = []
    for c in candidates:
        new_id = _insert(conn,
            f'INSERT INTO grow_candidates (conversation_id, category, rule) VALUES ({ph},{ph},{ph})',
            (conv_id, c.get('category', '기타'), c.get('rule', ''))
        )
        if new_id:
            ids.append(new_id)
    conn.close()
    return ids


def get_grow_candidates(conv_id: int = None, status: str = 'pending') -> list:
    conn = get_conn()
    ph = _ph()
    if conv_id:
        rows = _fetchall(conn,
            f'SELECT * FROM grow_candidates WHERE conversation_id={ph} AND status={ph} ORDER BY created_at DESC',
            (conv_id, status))
    else:
        rows = _fetchall(conn,
            f'SELECT * FROM grow_candidates WHERE status={ph} ORDER BY created_at DESC',
            (status,))
    conn.close()
    return rows


def promote_grow_candidate(candidate_id: int) -> int:
    """grow 후보 → 메인 patterns_db 승격"""
    conn = get_conn()
    ph = _ph()
    candidate = _fetchone(conn, f'SELECT * FROM grow_candidates WHERE id={ph}', (candidate_id,))
    conn.close()
    if not candidate:
        return None
    new_id = add_pattern(candidate['category'], candidate['rule'])
    conn = get_conn()
    _exec(conn,
        f'UPDATE grow_candidates SET status={ph}, promoted_pattern_id={ph} WHERE id={ph}',
        ('promoted', new_id, candidate_id))
    conn.close()
    return new_id


def reject_grow_candidate(candidate_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f'UPDATE grow_candidates SET status={ph} WHERE id={ph}', ('rejected', candidate_id))
    conn.close()


def get_grow_candidate_count(status: str = 'pending') -> int:
    conn = get_conn()
    ph = _ph()
    row = _fetchone(conn, f'SELECT COUNT(*) as cnt FROM grow_candidates WHERE status={ph}', (status,))
    conn.close()
    return (row or {}).get('cnt', 0)


def get_pattern_contribution():
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT patterns_fired, aligned FROM real_case_simulations WHERE patterns_fired IS NOT NULL')
    total = _fetchone(conn, 'SELECT SUM(aligned) as s, COUNT(*) as c FROM real_case_simulations')
    conn.close()
    overall_rate = (total.get('s') or 0) / max(total.get('c', 1), 1)
    stats = {}
    for row in rows:
        for pid in json.loads(row.get('patterns_fired') or '[]'):
            if pid not in stats:
                stats[pid] = {'fired': 0, 'aligned': 0}
            stats[pid]['fired'] += 1
            if row.get('aligned'):
                stats[pid]['aligned'] += 1
    result = []
    for pid, s in stats.items():
        rate = s['aligned'] / s['fired'] if s['fired'] else 0
        result.append({'id': pid, 'fired': s['fired'], 'aligned': s['aligned'],
                       'rate': round(rate * 100, 1), 'lift': round((rate - overall_rate) * 100, 1)})
    return sorted(result, key=lambda x: x['lift'], reverse=True), round(overall_rate * 100, 1)


def get_pattern_suggestions():
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT id, company, comparison_json, match_score FROM real_case_simulations ORDER BY match_score ASC')
    conn.close()
    result = []
    seen = set()
    for row in rows:
        comp = json.loads(row['comparison_json'])
        for p in comp.get('new_patterns', []):
            rule = p.get('rule', '').strip()
            if not rule or rule in seen:
                continue
            seen.add(rule)
            result.append({'category': p.get('category', '기타'), 'rule': rule,
                           'from_company': row['company'], 'case_score': row['match_score'], 'case_id': row['id']})
    return result


# ── 영상 기획 케이스 ──────────────────────────────────────

_VIDEO_SEED_CASES = [
    ("법무법인", "문제 제시 + 상담 CTA", "법정, 긴장감 속 변호사 완벽한 변론 → 판사 무죄 선고 → 페이드아웃"),
    ("뷰티클리닉 - 20대", "시술 전후 비교", "예쁜 여성이 걸어가는데 지나치는 남자들이 다 뒤돌아봄 → OO클리닉"),
    ("뷰티클리닉 - 중장년", "시술 전후 비교", "20대보다 탱탱한 피부의 중장년 여성 → 또래 역행 장면"),
    ("헬스장 - 소형", "몸매 변화 전후", "대형 헬스장 앞에서 커플이 줄 서며 '여기 진짜 맛집인가봐' 대화 → 시점 전환, 소형 헬스장 1:1 PT 장면"),
    ("헬스장 - 대형", "몸매 변화 전후", "사람들이 우르르 몰려오는 대형 헬스장 → 소셜 프루프로 증명"),
    ("식당/카페 - 디저트", "음식 클로즈업 + 맛있겠다", "커플이 격하게 싸우는데 사이로 케이크 마지막 조각에 포크 2개 꽂혀있음 → '10년차 연인도 싸우게 만드는 케이크' → OO카페"),
    ("부동산", "좋은 집 소개 + 문의", "직원이 전화 폭주에 으아아아 소리 지르며, 집 보러 사람들이 우르르 뒤따라옴 → '대입보다 경쟁률 높은 부동산' → OO부동산"),
    ("학원", "합격 후기 + 성적 수치", "주인공이 맨날 밖에서 놀고 수업 때 잠만 자는데 → 갑자기 눈이 활활 불타며 서울대 합격 → '공부는 재밌어야 한다' → OO학원"),
    ("펫샵/동물병원", "귀여운 동물 + 전문 케어", "젊은 여성 주변에 새끼 강아지들이 뛰어오고 재롱 피우는데 → 꿈에서 깨듯 화면 전환, 여성이 벌떡 일어남 → '세상 귀여운 강아지는 모두 여기에' → OO펫샵"),
    ("인테리어/리모델링", "시공 전후 + 견적 문의", "주부가 친구 초대해 집 보여줌, 친구 부러워하며 '1억 썼어?' → 반대로 그 친구가 초대하니 처음 주부가 말 못하고 허탈 → '나는 OO인테리어에서 5천만원에 이렇게 했어!'"),
    ("카이로프랙틱/정형외과", "통증 호소 + 치료 후 개선", "젊고 몸 좋은 사람이 헉헉거리며 뛰는데 → 옆에서 노인이 훨씬 빠르게 꼿꼿하게 앞서감 → '통증 100% 완치' → OO정형외과"),
    ("웨딩/스드메", "아름다운 웨딩 + 패키지 문의", "스카이캐슬 과외 선생님 '전적으로 절 믿으셔야 합니다' 장면 오마주 → 웨딩 플래너가 똑같은 포즈로"),
    ("세무사/회계사", "절세 팁 + 상담", "수돗꼭지에서 물이 나오다가 점점 돈으로 바뀌며 콸콸 새는데 → 수리기사가 땀 흘리며 고치려다 자꾸 새기만 함 → 다른 수리기사가 밀치고 한번에 탁 고치며 정장으로 전환"),
    ("보험", "위험 상황 + 가입 유도", "끼이익 차 사고 소리 → 화면 분할, 한쪽 컬러로 보험 있어서 수술+재활 완료, 한쪽 흑백으로 가족들이 힘들어하고 의사 선고 → 가족 욺"),
    ("이커머스/온라인쇼핑몰", "상품 + 할인 강조", "두두둥 어두웠다 밝아지며 드라마틱 리빌 → 모델이 상품 실제로 사용하는 장면 위주, 설명 최소화"),
    ("SaaS/IT솔루션", "기능 설명 + 데모 요청", "인하우스 마케터들이 엄청 바삐 우왕좌왕 → 화면 전환, 마케터 1명이 SaaS로 훨씬 빠르게 처리"),
    ("프랜차이즈 창업", "성공 사례 + 설명회", "손님 없는 매장에서 사장이 한숨 → 갑자기 사람들이 들어와 매장 싹 바꿔버림 → 손님 몰림 → OO치킨"),
    ("금융/대출", "금리 비교 + 신청 유도", "주인공이 대출 상징 인물 앞에서 절규하며 주저앉아 욺 → 우리 상품이 달려와서 드롭킥으로 차버림 → 주인공 일으켜서 안아줌"),
    ("카센터/자동차정비", "수리 전후 + 친절한 정비사", "옛날 시대극 느낌으로 웃기게 생긴 주인공이 '환자가 있소!! 아무도 없소?!!' 울먹이며 외치는데 → 점점 멀어지며 리어카 등장 → '정녕 아무도 없는거요!!' → 정비사가 뚝딱 고침 → '리어카도 당일 수리하는 OO카센터'"),
    ("이사/이삿짐센터", "이사 과정 편리함 + 파손 없음 강조", "올림픽 컬링 중계처럼 연출 → 상반신만 보이는 선수가 극도로 진지하게 자세 잡고 스톤 놓는 동작 → 놓는 순간 냉장고가 컬링 스톤처럼 슉 미끄러져 딱 제자리에 들어옴 → 아나운서 감탄 '완벽한 배치입니다!!' → '이사도 국가대표급으로'"),
]


def seed_video_cases():
    """초기 19케이스 DB 시드 (비어있을 때만)"""
    conn = get_conn()
    count = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM video_cases') or {}).get('cnt', 0)
    conn.close()
    if count > 0:
        return
    conn = get_conn()
    ph = _ph()
    for industry, boring, plan in _VIDEO_SEED_CASES:
        _insert(conn,
            f'INSERT INTO video_cases (industry, boring_direction, plan, source, status) VALUES ({ph},{ph},{ph},{ph},{ph})',
            [industry, boring, plan, 'seeded', 'approved'])
    conn.close()
    print(f"[DB] 영상 기획 케이스 시드 완료 ({len(_VIDEO_SEED_CASES)}개)")


def add_video_case(industry: str, boring_direction: str, plan: str,
                   source: str = 'extracted', status: str = 'pending') -> int:
    conn = get_conn()
    ph = _ph()
    new_id = _insert(conn,
        f'INSERT INTO video_cases (industry, boring_direction, plan, source, status) VALUES ({ph},{ph},{ph},{ph},{ph})',
        [industry, boring_direction, plan, source, status])
    conn.close()
    return new_id


def get_approved_video_cases() -> list:
    conn = get_conn()
    rows = _fetchall(conn, "SELECT * FROM video_cases WHERE status='approved' ORDER BY id ASC")
    conn.close()
    return rows


def get_pending_video_cases() -> list:
    conn = get_conn()
    rows = _fetchall(conn, "SELECT * FROM video_cases WHERE status='pending' ORDER BY created_at DESC")
    conn.close()
    return rows


def approve_video_case(case_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f"UPDATE video_cases SET status='approved' WHERE id={ph}", [case_id])
    conn.close()


def reject_video_case(case_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f"UPDATE video_cases SET status='rejected' WHERE id={ph}", [case_id])
    conn.close()


def get_video_case_counts() -> dict:
    conn = get_conn()
    approved = (_fetchone(conn, "SELECT COUNT(*) as cnt FROM video_cases WHERE status='approved'") or {}).get('cnt', 0)
    pending = (_fetchone(conn, "SELECT COUNT(*) as cnt FROM video_cases WHERE status='pending'") or {}).get('cnt', 0)
    conn.close()
    return {'approved': approved, 'pending': pending}


# ── 영상 기획 자동 시뮬레이션 ────────────────────────────

def save_video_simulation(brand: dict, brain_judgment: dict, draft: str, final_plan: str, round2: str = '') -> int:
    conn = get_conn()
    ph = _ph()
    new_id = _insert(conn,
        f'INSERT INTO video_simulations (brand_json, brain_judgment_json, draft, round2, final_plan) VALUES ({ph},{ph},{ph},{ph},{ph})',
        [json.dumps(brand, ensure_ascii=False),
         json.dumps(brain_judgment, ensure_ascii=False),
         draft, round2, final_plan])
    conn.close()
    return new_id


def get_video_simulations(limit: int = 20) -> list:
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn,
        f"SELECT * FROM video_simulations ORDER BY created_at DESC LIMIT {ph}", [limit])
    conn.close()
    for r in rows:
        r['brand'] = json.loads(r['brand_json'])
        r['brain_judgment'] = json.loads(r['brain_judgment_json'])
    return rows


def promote_video_simulation(sim_id: int) -> int:
    """시뮬레이션 결과 → video_cases 승인 + brain/video_cases.json 저장"""
    conn = get_conn()
    ph = _ph()
    row = _fetchone(conn, f'SELECT * FROM video_simulations WHERE id={ph}', [sim_id])
    conn.close()
    if not row:
        return None
    brand = json.loads(row['brand_json'])
    # draft에서 뻔한방향 추출 시도
    boring_dir = '(자동 시뮬레이션)'
    for line in (row.get('draft') or '').splitlines():
        if line.startswith('뻔한방향:'):
            boring_dir = line.split(':', 1)[-1].strip()
            break
    case_id = add_video_case(
        industry=brand.get('industry', ''),
        boring_direction=boring_dir,
        plan=row['final_plan'],
        source='simulation',
        status='approved'
    )
    conn = get_conn()
    _exec(conn, f"UPDATE video_simulations SET status='approved' WHERE id={ph}", [sim_id])
    conn.close()

    # brain/video_cases.json에 누적 저장 (GitHub 백업용)
    try:
        json_path = BASE_DIR / 'brain' / 'video_cases.json'
        existing = []
        if json_path.exists():
            with open(json_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        existing.append({
            'id': case_id,
            'sim_id': sim_id,
            'brand_name': brand.get('brand_name', ''),
            'industry': brand.get('industry', ''),
            'product': brand.get('product_name', ''),
            'target': brand.get('target', ''),
            'tone': brand.get('tone', ''),
            'boring_direction': boring_dir,
            'draft': row.get('draft', ''),
            'round2': row.get('round2', ''),
            'final_plan': row['final_plan'],
            'created_at': row.get('created_at', ''),
        })
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'[video_cases.json 저장 실패] {e}')

    return case_id


def get_approved_video_simulations(limit: int = 200) -> list:
    """승인된 시뮬레이션 전체 데이터 반환 (결과 케이스 페이지용)"""
    conn = get_conn()
    rows = _fetchall(conn,
        f"SELECT * FROM video_simulations WHERE status='approved' ORDER BY created_at DESC LIMIT {limit}")
    conn.close()
    for r in rows:
        r['brand'] = json.loads(r['brand_json'])
        r['brain_judgment'] = json.loads(r['brain_judgment_json'])
    return rows


def dismiss_video_simulation(sim_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f"UPDATE video_simulations SET status='dismissed' WHERE id={ph}", [sim_id])
    conn.close()


def get_video_simulation_counts() -> dict:
    conn = get_conn()
    pending = (_fetchone(conn, "SELECT COUNT(*) as cnt FROM video_simulations WHERE status='pending'") or {}).get('cnt', 0)
    total = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM video_simulations') or {}).get('cnt', 0)
    conn.close()
    return {'pending': pending, 'total': total}


def get_missed_frequency(limit=20):
    conn = get_conn()
    rows = _fetchall(conn, 'SELECT comparison_json FROM real_case_simulations')
    conn.close()
    freq = {}
    for row in rows:
        comp = json.loads(row['comparison_json'])
        for item in comp.get('what_agent_missed', []):
            item = item.strip()
            if item:
                freq[item] = freq.get(item, 0) + 1
    return sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]


def get_match_score_trend(limit=60):
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT match_score, created_at, company, aligned FROM real_case_simulations ORDER BY id ASC LIMIT {ph}', [limit])
    conn.close()
    return rows


# ── 채팅 관련 ─────────────────────────────────────────────

def start_conversation(user_name: str, user_role: str, topic: str = '', section: str = 'marketing') -> int:
    conn = get_conn()
    ph = _ph()
    new_id = _insert(conn,
                     f'INSERT INTO conversations (user_name, user_role, topic, section) VALUES ({ph},{ph},{ph},{ph})',
                     [user_name, user_role, topic, section])
    conn.close()
    return new_id


def save_message(conversation_id: int, role: str, content: str, user_name: str = '') -> int:
    conn = get_conn()
    ph = _ph()
    msg_id = _insert(conn,
                     f'INSERT INTO conversation_messages (conversation_id, role, content, user_name) VALUES ({ph},{ph},{ph},{ph})',
                     [conversation_id, role, content, user_name])
    _exec(conn, f'UPDATE conversations SET message_count = message_count + 1 WHERE id={ph}', [conversation_id])
    conn.close()
    return msg_id


def get_conversation_messages(conversation_id: int) -> list:
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT * FROM conversation_messages WHERE conversation_id={ph} ORDER BY id ASC', [conversation_id])
    conn.close()
    return rows


def get_conversation_by_id(conversation_id: int):
    conn = get_conn()
    ph = _ph()
    row = _fetchone(conn, f'SELECT * FROM conversations WHERE id={ph}', [conversation_id])
    conn.close()
    return row


def update_conversation_topic(conversation_id: int, topic: str):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f'UPDATE conversations SET topic={ph} WHERE id={ph}', [topic, conversation_id])
    conn.close()


def get_all_conversations(limit: int = 100) -> list:
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn, f'SELECT * FROM conversations ORDER BY created_at DESC LIMIT {ph}', [limit])
    conn.close()
    return rows


def get_pending_pattern_requests() -> list:
    conn = get_conn()
    ph = _ph()
    rows = _fetchall(conn,
                     f'''SELECT pr.*, c.user_name as conv_user, c.topic as conv_topic
                         FROM pattern_requests pr
                         JOIN conversations c ON pr.conversation_id=c.id
                         WHERE pr.status={ph} ORDER BY pr.created_at DESC''',
                     ['pending'])
    conn.close()
    return rows


def get_pending_pattern_request_count() -> int:
    conn = get_conn()
    ph = _ph()
    row = _fetchone(conn, f"SELECT COUNT(*) as cnt FROM pattern_requests WHERE status={ph}", ['pending'])
    conn.close()
    return (row or {}).get('cnt', 0)


def add_pattern_request(conversation_id: int, proposed_category: str,
                        proposed_rule: str, requested_by: str, context: str = '') -> int:
    conn = get_conn()
    ph = _ph()
    req_id = _insert(conn,
                     f'INSERT INTO pattern_requests (conversation_id, proposed_category, proposed_rule, requested_by, context) VALUES ({ph},{ph},{ph},{ph},{ph})',
                     [conversation_id, proposed_category, proposed_rule, requested_by, context])
    conn.close()
    return req_id


def approve_pattern_request(request_id: int) -> int:
    conn = get_conn()
    ph = _ph()
    row = _fetchone(conn, f'SELECT * FROM pattern_requests WHERE id={ph}', [request_id])
    if not row:
        conn.close()
        return -1
    _exec(conn, f"UPDATE pattern_requests SET status='approved', reviewed_at=({_now()}) WHERE id={ph}", [request_id])
    conn.close()
    return add_pattern(row['proposed_category'], row['proposed_rule'])


def dismiss_pattern_request(request_id: int):
    conn = get_conn()
    ph = _ph()
    _exec(conn, f"UPDATE pattern_requests SET status='dismissed', reviewed_at=({_now()}) WHERE id={ph}", [request_id])
    conn.close()


def get_chat_stats() -> dict:
    conn = get_conn()
    ph = _ph()
    total_conv = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM conversations') or {}).get('cnt', 0)
    total_msg = (_fetchone(conn, 'SELECT COUNT(*) as cnt FROM conversation_messages') or {}).get('cnt', 0)
    pending = (_fetchone(conn, f"SELECT COUNT(*) as cnt FROM pattern_requests WHERE status={ph}", ['pending']) or {}).get('cnt', 0)
    conn.close()
    return {'total_conversations': total_conv, 'total_messages': total_msg, 'pending_requests': pending}
