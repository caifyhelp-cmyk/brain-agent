# -*- coding: utf-8 -*-
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "thinking_brain.db"
PATTERNS_PATH = BASE_DIR / "brain" / "patterns.json"

# Render가 제공하는 PostgreSQL URL (없으면 SQLite 사용)
_DATABASE_URL = os.environ.get('DATABASE_URL', '')
if _DATABASE_URL.startswith('postgres://'):
    _DATABASE_URL = _DATABASE_URL.replace('postgres://', 'postgresql://', 1)

_USE_PG = bool(_DATABASE_URL)


# ── 커넥션 & 쿼리 헬퍼 ───────────────────────────────────

def get_conn():
    if _USE_PG:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(_DATABASE_URL, cursor_factory=RealDictCursor)
        return conn
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
    ]

    for sql in tables:
        _exec(conn, sql)

    conn.close()

    # 패턴 JSON → DB 시드 (patterns_db가 비어있을 때만)
    _seed_patterns_from_json()


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
