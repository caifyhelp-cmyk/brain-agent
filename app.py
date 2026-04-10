# -*- coding: utf-8 -*-
import json
import os
import threading
import time
import webbrowser
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from apscheduler.schedulers.background import BackgroundScheduler

import db
import simulator
import chat as chat_engine
from config_helper import get_config

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.environ.get('SECRET_KEY', 'brain-agent-secret-2024')

# gunicorn으로 실행 시에도 DB 초기화
db.init_db()


def _owner_pin():
    return str(get_config()['owner_pin'])
scheduler = BackgroundScheduler(timezone="Asia/Seoul")


# ── 스케줄 작업 ──────────────────────────────────────────

def job_daily_simulations():
    count = get_config().get('simulations_per_day', 5)
    print(f"[자동 실행] 오늘의 시뮬레이션 {count}건 시작")
    for i in range(count):
        try:
            simulator.run_simulation()
            print(f"  {i+1}/{count} 완료")
        except Exception as e:
            print(f"  오류: {e}")


def job_weekly_report():
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    print(f"[자동 실행] 주간 리포트 생성 중 ({week_start})")
    try:
        simulator.generate_weekly_report(week_start)
        print("  리포트 생성 완료")
    except Exception as e:
        print(f"  오류: {e}")


# ── 라우트 ───────────────────────────────────────────────

@app.route('/')
def dashboard():
    has_key = bool(get_config().get('openai_api_key', '').strip())
    if not has_key:
        return redirect(url_for('setup'))

    stats = db.get_dashboard_stats()
    recent = db.get_recent_simulations(8)
    flagged = db.get_flagged_simulations()
    top_patterns = db.get_pattern_frequency(5)
    real_stats = db.get_real_case_stats()
    show_sim_btn = real_stats['total'] >= 50 and stats['total_patterns'] >= 100
    return render_template('dashboard.html',
                           stats=stats, recent=recent,
                           flagged=flagged, top_patterns=top_patterns,
                           show_sim_btn=show_sim_btn,
                           real_case_total=real_stats['total'])


@app.route('/setup', methods=['GET', 'POST'])
def setup():
    config = get_config()
    if request.method == 'POST':
        api_key = request.form.get('api_key', '').strip()
        sims = int(request.form.get('simulations_per_day', 5))
        hour = int(request.form.get('simulation_hour', 9))
        # 로컬 환경에서만 config.json 저장
        if not os.environ.get('DATABASE_URL'):
            CONFIG_PATH = BASE_DIR / "config.json"
            new_cfg = {'openai_api_key': api_key, 'simulations_per_day': sims,
                       'simulation_hour': hour, 'owner_pin': config.get('owner_pin', '1234')}
            CONFIG_PATH.write_text(json.dumps(new_cfg, ensure_ascii=False, indent=2), encoding='utf-8')
        _reschedule(hour)
        return redirect(url_for('dashboard'))
    return render_template('setup.html', config=config)


@app.route('/report')
def report():
    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    reports = db.get_weekly_reports(8)
    current_report = next((r for r in reports if r['week_start'] == week_start), None)
    if not current_report and reports:
        current_report = reports[0]
    return render_template('report.html',
                           current_report=current_report,
                           all_reports=reports,
                           week_start=week_start)


@app.route('/patterns')
def patterns():
    patterns_data = db.get_patterns()
    categories = {}
    for p in patterns_data['patterns']:
        cat = p['category']
        categories.setdefault(cat, []).append(p)
    return render_template('patterns.html',
                           categories=categories,
                           axes=patterns_data['axes'],
                           total=len(patterns_data['patterns']))


# ── 뇌 성장 라우트 ───────────────────────────────────────

@app.route('/grow')
def grow():
    section = request.args.get('section', 'marketing')
    content_type = request.args.get('type', 'youtube')
    pending = db.get_pending_pattern_request_count()
    return render_template('grow.html', section=section,
                           content_type=content_type, pending=pending)


@app.route('/api/grow/start', methods=['POST'])
def api_grow_start():
    data = request.json
    user_name = data.get('user_name', '').strip()
    section = data.get('section', 'marketing')
    content_type = data.get('content_type', '')
    pin = data.get('pin', '').strip()

    if not user_name:
        return jsonify({'ok': False, 'error': '이름을 입력하세요'})

    is_owner = (pin == _owner_pin())
    if is_owner:
        session['is_owner'] = True

    full_section = section
    if section == 'content':
        full_section = f'content_{content_type}' if content_type else 'content_youtube'

    topic_map = {'marketing': '마케팅', 'planning': '기획',
                 'content_youtube': '콘텐츠 — 유튜브', 'content_blog': '콘텐츠 — 블로그'}
    topic = topic_map.get(full_section, full_section)

    user_role = 'owner' if is_owner else 'employee'
    conv_id = db.start_conversation(user_name, user_role, topic, full_section)
    return jsonify({'ok': True, 'conversation_id': conv_id, 'section': full_section})


@app.route('/api/grow/message', methods=['POST'])
def api_grow_message():
    data = request.json
    conv_id = int(data.get('conversation_id', 0))
    user_message = data.get('message', '').strip()
    user_name = data.get('user_name', '사용자')
    section = data.get('section', 'marketing')

    if not conv_id or not user_message:
        return jsonify({'ok': False, 'error': '입력값 누락'})

    db.save_message(conv_id, 'user', user_message, user_name)

    try:
        brain_reply = chat_engine.get_brain_response(conv_id, user_message, user_name, section)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

    msg_id = db.save_message(conv_id, 'assistant', brain_reply, '뇌')
    return jsonify({'ok': True, 'reply': brain_reply, 'message_id': msg_id})


@app.route('/api/grow/new-case', methods=['POST'])
def api_grow_new_case():
    content_type = request.json.get('content_type', 'youtube')
    try:
        case = chat_engine.generate_content_case(content_type)
        return jsonify({'ok': True, 'case': case})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/grow/request-pattern', methods=['POST'])
def api_grow_request_pattern():
    data = request.json
    conv_id = int(data.get('conversation_id', 0))
    category = data.get('category', '기타').strip()
    rule = data.get('rule', '').strip()
    requested_by = data.get('requested_by', '').strip()
    context = data.get('context', '').strip()

    if not rule:
        return jsonify({'ok': False, 'error': '패턴 내용을 입력하세요'})

    req_id = db.add_pattern_request(conv_id, category, rule, requested_by, context)
    return jsonify({'ok': True, 'request_id': req_id})


# ── API ──────────────────────────────────────────────────

@app.route('/api/simulate', methods=['POST'])
def api_simulate():
    count = int(request.json.get('count', 1))
    results = []
    for _ in range(count):
        try:
            scenario, result, auto_added = simulator.run_simulation()
            results.append({
                'ok': True,
                'industry': scenario.get('industry', ''),
                'confidence': result.get('confidence', 0),
                'auto_added': len(auto_added),
                'new_pattern_rules': [p['rule'] for p in auto_added]
            })
        except Exception as e:
            results.append({'ok': False, 'error': str(e)})
    return jsonify({'results': results})


@app.route('/api/dismiss/<int:sim_id>', methods=['POST'])
def api_dismiss(sim_id):
    db.dismiss_simulation(sim_id)
    return jsonify({'status': 'ok'})


@app.route('/api/add-pattern', methods=['POST'])
def api_add_pattern():
    data = request.json
    rule = data.get('rule', '').strip()
    if not rule:
        return jsonify({'status': 'error', 'message': '패턴 내용을 입력하세요'})
    category = data.get('category', '기타')
    sim_id = data.get('simulation_id')
    new_id = db.add_pattern(category, rule, sim_id)
    if sim_id:
        db.dismiss_simulation(sim_id)
    return jsonify({'status': 'ok', 'new_id': new_id})


@app.route('/api/edit-pattern/<int:pattern_id>', methods=['POST'])
def api_edit_pattern(pattern_id):
    data = request.json
    new_rule = data.get('rule', '').strip()
    if not new_rule:
        return jsonify({'status': 'error', 'message': '패턴 내용을 입력하세요'})
    db.edit_pattern(pattern_id, new_rule)
    return jsonify({'status': 'ok'})


@app.route('/api/delete-pattern/<int:pattern_id>', methods=['POST'])
def api_delete_pattern(pattern_id):
    db.delete_pattern(pattern_id)
    return jsonify({'status': 'ok'})


@app.route('/api/generate-report', methods=['POST'])
def api_generate_report():
    week_start = request.json.get('week_start')
    report = simulator.generate_weekly_report(week_start)
    if report:
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error', 'message': '이번 주 시뮬레이션 데이터가 없습니다'})


@app.route('/real-cases')
def real_cases():
    recent = db.get_recent_real_case_simulations(10)
    flagged = db.get_flagged_real_case_simulations()
    stats = db.get_real_case_stats()
    return render_template('real_cases.html', recent=recent, flagged=flagged, stats=stats)


@app.route('/api/simulate-real', methods=['POST'])
def api_simulate_real():
    try:
        results, newly_generated = simulator.run_real_case_batch(10)
        total_added = sum(r.get('auto_added', 0) for r in results if r.get('ok'))
        aligned_count = sum(1 for r in results if r.get('ok') and r.get('aligned'))
        avg_score = round(
            sum(r.get('match_score', 0) for r in results if r.get('ok')) / max(len(results), 1), 1
        )
        return jsonify({
            'ok': True,
            'results': results,
            'summary': {
                'total': len(results),
                'aligned': aligned_count,
                'avg_score': avg_score,
                'patterns_added': total_added,
                'newly_generated': newly_generated
            }
        })

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/dismiss-real/<int:sim_id>', methods=['POST'])
def api_dismiss_real(sim_id):
    db.dismiss_real_case(sim_id)
    return jsonify({'status': 'ok'})


@app.route('/api/reprocess-real', methods=['POST'])
def api_reprocess_real():
    try:
        full = request.json.get('full', True)
        result = simulator.reprocess_existing_real_cases(full=full)
        return jsonify({'ok': True, 'result': result})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/ask')
def ask():
    return render_template('ask.html')


@app.route('/api/ask', methods=['POST'])
def api_ask():
    data = request.json
    scenario = {
        'industry': data.get('industry', '').strip(),
        'company_size': data.get('company_size', '중소'),
        'challenge': data.get('challenge', '').strip(),
        'context': data.get('context', '').strip(),
        'goal': data.get('goal', '').strip(),
        'assets': data.get('assets', '').strip(),
        'constraints': data.get('constraints', '').strip(),
    }
    if not scenario['context']:
        return jsonify({'status': 'error', 'message': '상황 설명을 입력하세요'})
    try:
        result = simulator.evaluate_with_brain(scenario)
        db.save_ask_session(scenario, result)
        patterns_data = db.get_patterns()
        pattern_map = {p['id']: p for p in patterns_data['patterns']}
        fired_patterns = [pattern_map[pid] for pid in result.get('patterns_fired', []) if pid in pattern_map]
        return jsonify({'status': 'ok', 'result': result, 'fired_patterns': fired_patterns})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/export-prompt', methods=['GET'])
def api_export_prompt():
    patterns_data = db.get_patterns()
    patterns = patterns_data['patterns']
    axes = patterns_data['axes']
    by_cat = {}
    for p in patterns:
        by_cat.setdefault(p['category'], []).append(p)
    lines = []
    lines.append("# 마케터 사고로직 에이전트 — 자동 생성 프롬프트")
    lines.append(f"# 패턴 {len(patterns)}개 기준 | 생성일: {date.today().isoformat()}\n")
    lines.append("## 핵심 3축")
    for a in axes:
        lines.append(f"- {a['name']}: {a['description']}")
    lines.append("")
    lines.append("## 고유 사고 시그니처")
    lines.append("① 판 바꾸기: 약점 보완 X, 경쟁 축 자체를 바꾼다")
    lines.append("② 타겟 착시 간파: 인구통계 겹침 ≠ 구매 의도 겹침")
    lines.append("③ 증명 우선: 말로 설명 X, 수치/이벤트/구조로 증명")
    lines.append("④ 레버리지 연결: 확정된 것을 미확정 협상 도구로 활용")
    lines.append("⑤ 수치 타겟화: 막연한 그룹 아닌 비율/수치로 구체화")
    lines.append("")
    lines.append("## 판단 패턴 전체 목록")
    for cat, pats in by_cat.items():
        lines.append(f"\n### {cat}")
        for p in pats:
            lines.append(f"- [{p['id']}] {p['rule']}")
    lines.append("")
    lines.append("## 판단 기준")
    lines.append("- 위 패턴 중 해당하는 것을 발동시켜 판단하라")
    lines.append("- 일반적인 마케팅 조언 금지, 이 패턴들로만 판단")
    lines.append("- 각 액션에 수치/측정기준 포함 필수")
    lines.append("- 패턴으로 커버 안 되는 부분은 gaps로 명시")
    prompt_text = "\n".join(lines)
    return jsonify({'status': 'ok', 'prompt': prompt_text, 'pattern_count': len(patterns)})


@app.route('/mine')
def mine():
    suggestions = db.get_pattern_suggestions()
    trend = db.get_match_score_trend(60)
    missed = db.get_missed_frequency(20)
    by_cat = {}
    for s in suggestions:
        by_cat.setdefault(s['category'], []).append(s)
    patterns_data = db.get_patterns()
    existing_count = len(patterns_data['patterns'])
    scores = [t['match_score'] for t in trend]
    all_avg = round(sum(scores) / len(scores), 1) if scores else 0
    trend_avg = round(sum(scores[-20:]) / min(len(scores), 20), 1) if scores else 0
    contribution, overall_rate = db.get_pattern_contribution()
    patterns_data = db.get_patterns()
    pattern_map = {p['id']: p for p in patterns_data['patterns']}
    top_patterns = [dict(**c, rule=pattern_map[c['id']]['rule'], category=pattern_map[c['id']]['category'])
                    for c in contribution[:15] if c['id'] in pattern_map]
    dead_patterns = [dict(**c, rule=pattern_map[c['id']]['rule'], category=pattern_map[c['id']]['category'])
                     for c in contribution[-10:] if c['id'] in pattern_map and c['fired'] > 0 and c['rate'] < overall_rate]
    return render_template('mine.html',
                           suggestions=suggestions,
                           by_cat=by_cat,
                           trend=trend,
                           missed=missed,
                           existing_count=existing_count,
                           total_suggestions=len(suggestions),
                           all_avg=all_avg,
                           trend_avg=trend_avg,
                           top_patterns=top_patterns,
                           dead_patterns=dead_patterns,
                           overall_rate=overall_rate)


@app.route('/train')
def train():
    recent_sessions = db.get_recent_training_sessions(5)
    return render_template('train.html', recent_sessions=recent_sessions)


@app.route('/api/new-scenario', methods=['POST'])
def api_new_scenario():
    try:
        scenario = simulator.generate_stress_scenario()
        return jsonify({'status': 'ok', 'scenario': scenario})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/evaluate', methods=['POST'])
def api_evaluate():
    data = request.json
    scenario = data.get('scenario')
    user_response = data.get('user_response', '').strip()
    if not scenario or not user_response:
        return jsonify({'status': 'error', 'message': '시나리오와 판단 내용이 필요합니다'})
    try:
        result = simulator.evaluate_user_response(scenario, user_response)
        return jsonify({'status': 'ok', 'evaluation': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/synthesize', methods=['POST'])
def api_synthesize():
    try:
        result = simulator.synthesize_patterns()
        return jsonify({'status': 'ok', 'synthesis': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


# ── 채팅 라우트 ──────────────────────────────────────────

@app.route('/chat')
def chat_start():
    pending = db.get_pending_pattern_request_count()
    is_owner = session.get('is_owner', False)
    return render_template('chat_start.html', pending=pending, is_owner=is_owner)


@app.route('/chat/<int:conv_id>')
def chat_room(conv_id):
    conv = db.get_conversation_by_id(conv_id)
    if not conv:
        return redirect(url_for('chat_start'))
    messages = db.get_conversation_messages(conv_id)
    is_owner = session.get('is_owner', False)
    pending = db.get_pending_pattern_request_count()
    return render_template('chat.html', conv=conv, messages=messages,
                           is_owner=is_owner, pending=pending)


@app.route('/api/chat/start', methods=['POST'])
def api_chat_start():
    data = request.json
    user_name = data.get('user_name', '').strip()
    user_role = data.get('user_role', 'employee')
    topic = data.get('topic', '').strip()
    pin = data.get('pin', '').strip()

    if not user_name:
        return jsonify({'ok': False, 'error': '이름을 입력하세요'})

    if user_role == 'owner':
        if pin != _owner_pin():
            return jsonify({'ok': False, 'error': 'PIN이 틀렸습니다'})
        session['is_owner'] = True
    else:
        session['is_owner'] = False

    conv_id = db.start_conversation(user_name, user_role, topic, 'general')
    return jsonify({'ok': True, 'conversation_id': conv_id})


@app.route('/api/chat/message', methods=['POST'])
def api_chat_message():
    data = request.json
    conv_id = int(data.get('conversation_id', 0))
    user_message = data.get('message', '').strip()
    user_name = data.get('user_name', '사용자')

    if not conv_id or not user_message:
        return jsonify({'ok': False, 'error': '입력값 누락'})

    conv = db.get_conversation_by_id(conv_id)
    if not conv:
        return jsonify({'ok': False, 'error': '대화를 찾을 수 없습니다'})

    # 첫 메시지로 topic 자동 설정
    if not conv['topic'] and conv['message_count'] == 0:
        db.update_conversation_topic(conv_id, user_message[:40])

    db.save_message(conv_id, 'user', user_message, user_name)

    try:
        brain_reply = chat_engine.get_brain_response(conv_id, user_message, user_name)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

    msg_id = db.save_message(conv_id, 'assistant', brain_reply, '뇌')
    return jsonify({'ok': True, 'reply': brain_reply, 'message_id': msg_id})


@app.route('/api/chat/request-pattern', methods=['POST'])
def api_chat_request_pattern():
    data = request.json
    conv_id = int(data.get('conversation_id', 0))
    category = data.get('category', '기타').strip()
    rule = data.get('rule', '').strip()
    requested_by = data.get('requested_by', '').strip()
    context = data.get('context', '').strip()

    if not rule:
        return jsonify({'ok': False, 'error': '패턴 내용을 입력하세요'})

    req_id = db.add_pattern_request(conv_id, category, rule, requested_by, context)
    return jsonify({'ok': True, 'request_id': req_id})


@app.route('/api/chat/extract-patterns', methods=['POST'])
def api_chat_extract_patterns():
    conv_id = int(request.json.get('conversation_id', 0))
    if not conv_id:
        return jsonify({'ok': False, 'error': '대화 ID 누락'})
    try:
        patterns = chat_engine.extract_patterns_from_conversation(conv_id)
        return jsonify({'ok': True, 'patterns': patterns})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/chat/add-pattern-direct', methods=['POST'])
def api_chat_add_pattern_direct():
    """오너가 대화 중 직접 패턴 추가"""
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    data = request.json
    category = data.get('category', '기타').strip()
    rule = data.get('rule', '').strip()
    if not rule:
        return jsonify({'ok': False, 'error': '패턴 내용을 입력하세요'})
    new_id = db.add_pattern(category, rule)
    return jsonify({'ok': True, 'new_id': new_id})


# ── 로그 / 리뷰 라우트 (오너 전용) ───────────────────────

@app.route('/logs')
def logs():
    if not session.get('is_owner'):
        return redirect(url_for('chat_start'))
    conversations = db.get_all_conversations(100)
    pending = db.get_pending_pattern_request_count()
    return render_template('logs.html', conversations=conversations, pending=pending)


@app.route('/logs/<int:conv_id>')
def log_detail(conv_id):
    if not session.get('is_owner'):
        return redirect(url_for('chat_start'))
    conv = db.get_conversation_by_id(conv_id)
    messages = db.get_conversation_messages(conv_id)
    pending = db.get_pending_pattern_request_count()
    return render_template('log_detail.html', conv=conv, messages=messages, pending=pending)


@app.route('/review')
def review():
    if not session.get('is_owner'):
        return redirect(url_for('chat_start'))
    requests_list = db.get_pending_pattern_requests()
    pending = db.get_pending_pattern_request_count()
    return render_template('review.html', requests=requests_list, pending=pending)


@app.route('/api/review/approve/<int:req_id>', methods=['POST'])
def api_review_approve(req_id):
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    new_id = db.approve_pattern_request(req_id)
    return jsonify({'ok': True, 'new_pattern_id': new_id})


@app.route('/api/review/dismiss/<int:req_id>', methods=['POST'])
def api_review_dismiss(req_id):
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    db.dismiss_pattern_request(req_id)
    return jsonify({'ok': True})


# ── 유틸 ─────────────────────────────────────────────────

def _reschedule(sim_hour):
    try:
        scheduler.reschedule_job('daily_sim', trigger='cron', hour=sim_hour, minute=0)
    except Exception:
        pass


# ── 메인 ─────────────────────────────────────────────────

if __name__ == '__main__':
    db.init_db()

    sim_hour = get_config().get('simulation_hour', 9)

    scheduler.add_job(job_daily_simulations, 'cron', hour=sim_hour, minute=0, id='daily_sim')
    scheduler.add_job(job_weekly_report, 'cron', day_of_week='mon', hour=8, minute=0, id='weekly_report')
    scheduler.start()

    def open_browser():
        time.sleep(1.5)
        webbrowser.open('http://localhost:5000')

    threading.Thread(target=open_browser, daemon=True).start()

    print("=" * 40)
    print("  뇌 에이전트 실행 중")
    print("  http://localhost:5000")
    print("  종료: Ctrl+C")
    print("=" * 40)

    app.run(debug=False, use_reloader=False, port=5000, threaded=True)
