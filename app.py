# -*- coding: utf-8 -*-
import json
import os
import threading
import time
import webbrowser
from datetime import date, timedelta
from pathlib import Path

import queue
import uuid
from flask import Flask, render_template, jsonify, request, redirect, url_for, session, Response, stream_with_context
from apscheduler.schedulers.background import BackgroundScheduler

import db
import simulator
import video_simulator
import chat as chat_engine
from config_helper import get_config

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.environ.get('SECRET_KEY', 'brain-agent-secret-2024')

import traceback as _traceback

@app.errorhandler(Exception)
def _handle_all_exceptions(e):
    tb = _traceback.format_exc()
    print(f"[UNHANDLED] {type(e).__name__}: {e}\n{tb}")
    return jsonify({'error': str(e), 'type': type(e).__name__}), 500

# gunicorn으로 실행 시에도 DB 초기화
db.init_db()

# 임베딩 초기화 — 백그라운드에서 실행 (앱 응답 지연 없음)
def _init_embeddings_bg():
    try:
        import embeddings
        count = embeddings.ensure_embeddings()
        if count:
            print(f"[임베딩] 신규 {count}개 생성 완료")
    except Exception as e:
        print(f"[임베딩] 초기화 실패 (폴백 모드 유지): {e}")

threading.Thread(target=_init_embeddings_bg, daemon=True).start()

scheduler = BackgroundScheduler(timezone="Asia/Seoul")


def _owner_pin():
    return str(get_config()['owner_pin'])


# 스케줄러 초기화 — gunicorn 포함 모든 실행 환경에서 동작
def _init_scheduler():
    sim_hour = get_config().get('simulation_hour', 9)
    try:
        scheduler.add_job(job_daily_simulations, 'cron', hour=sim_hour, minute=0, id='daily_sim')
        scheduler.add_job(job_weekly_report, 'cron', day_of_week='mon', hour=8, minute=0, id='weekly_report')
        video_hour = get_config().get('video_simulation_hour', 10)
        scheduler.add_job(job_video_simulations, 'cron', hour=video_hour, minute=30, id='video_sim')
        scheduler.start()
        import atexit
        atexit.register(lambda: scheduler.shutdown(wait=False))
        print(f"[스케줄러] 시작 완료 - 매일 {sim_hour}시 마케팅 / {video_hour}시 30분 영상 시뮬레이션")
    except Exception as e:
        print(f"[스케줄러] 초기화 오류: {e}")

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


def job_video_simulations():
    count = get_config().get('video_simulations_per_day', 3)
    print(f"[영상 자동 시뮬] {count}건 시작")
    for i in range(count):
        try:
            video_simulator.run_video_simulation()
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

_init_scheduler()


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
    phase = chat_engine.get_current_phase()
    return jsonify({'ok': True, 'conversation_id': conv_id, 'section': full_section, 'phase': phase})


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

    # 6메시지(3턴)마다 패턴 후보 자동 추출 → grow_candidates (별개 방)
    conv_after = db.get_conversation_by_id(conv_id)
    msg_count = conv_after.get('message_count', 0) if conv_after else 0
    new_candidates = []
    if msg_count > 0 and msg_count % 6 == 0:
        try:
            raw = chat_engine.extract_patterns_from_conversation(conv_id)
            if raw:
                db.save_grow_candidates(conv_id, raw)
                new_candidates = raw
        except Exception:
            pass

    return jsonify({'ok': True, 'reply': brain_reply, 'message_id': msg_id,
                    'new_candidates': new_candidates})


@app.route('/api/grow/new-case', methods=['POST'])
def api_grow_new_case():
    content_type = request.json.get('content_type', 'youtube')
    try:
        case = chat_engine.generate_content_case(content_type)
        return jsonify({'ok': True, 'case': case})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/grow/new-opening', methods=['POST'])
def api_grow_new_opening():
    """새 케이스를 뇌 메시지로 생성하고 대화에 저장 (단계별)"""
    data = request.json
    conv_id = int(data.get('conversation_id', 0))
    section = data.get('section', 'marketing')
    phase = int(data.get('phase', 1))
    if not conv_id:
        return jsonify({'ok': False, 'error': '대화 ID 누락'})
    try:
        if phase == 2:
            opening = chat_engine.generate_phase2_opening(section)
        else:
            opening = chat_engine.generate_opening_message(section)
        db.save_message(conv_id, 'assistant', opening, '뇌')
        return jsonify({'ok': True, 'reply': opening})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/grow/candidates', methods=['GET'])
def api_grow_candidates():
    conv_id = request.args.get('conv_id', type=int)
    candidates = db.get_grow_candidates(conv_id=conv_id, status='pending')
    return jsonify({'ok': True, 'candidates': candidates})


@app.route('/api/grow/promote/<int:cid>', methods=['POST'])
def api_grow_promote(cid):
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    new_id = db.promote_grow_candidate(cid)
    return jsonify({'ok': True, 'new_pattern_id': new_id})


@app.route('/api/grow/reject/<int:cid>', methods=['POST'])
def api_grow_reject(cid):
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    db.reject_grow_candidate(cid)
    return jsonify({'ok': True})


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
    # 신규 패턴 임베딩 백그라운드 생성
    threading.Thread(target=_init_embeddings_bg, daemon=True).start()
    return jsonify({'status': 'ok', 'new_id': new_id})


@app.route('/api/edit-pattern/<int:pattern_id>', methods=['POST'])
def api_edit_pattern(pattern_id):
    data = request.json
    new_rule = data.get('rule', '').strip()
    if not new_rule:
        return jsonify({'status': 'error', 'message': '패턴 내용을 입력하세요'})
    db.edit_pattern(pattern_id, new_rule)
    try:
        import embeddings
        embeddings.invalidate_pattern(pattern_id)
        threading.Thread(target=_init_embeddings_bg, daemon=True).start()
    except Exception:
        pass
    return jsonify({'status': 'ok'})


@app.route('/api/delete-pattern/<int:pattern_id>', methods=['POST'])
def api_delete_pattern(pattern_id):
    db.delete_pattern(pattern_id)
    try:
        import embeddings
        embeddings.invalidate_pattern(pattern_id)
    except Exception:
        pass
    return jsonify({'status': 'ok'})


@app.route('/api/admin/rebuild-embeddings', methods=['POST'])
def api_rebuild_embeddings():
    """관리자 전용 — 전체 임베딩 재생성"""
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    try:
        import embeddings
        count = embeddings.ensure_embeddings()
        stats = embeddings.get_embedding_stats()
        return jsonify({'ok': True, 'generated': count, 'stats': stats})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/admin/embedding-stats', methods=['GET'])
def api_embedding_stats():
    """임베딩 현황 조회"""
    try:
        import embeddings
        stats = embeddings.get_embedding_stats()
        return jsonify({'ok': True, **stats})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@app.route('/api/research', methods=['POST'])
def api_research():
    """웹 리서치 어시스턴트 전용 뇌 에이전트 엔드포인트.
    Request JSON: {"situation": "리서치 주제 및 컨텍스트"}
    Response JSON: {"ok": true, "judgment": "...", "action": "...", "reason": "..."}
    """
    from agent import analyze as _analyze
    data = request.json or {}
    situation = data.get('situation', '').strip()
    if not situation:
        return jsonify({'ok': False, 'error': 'situation 필드가 필요합니다.'}), 400
    try:
        result = _analyze(situation)
        # matched_patterns: [{category, rule}, ...] 형태
        raw_patterns = result.get('matched_patterns', [])
        # 케이스스터디형 필터링 후 카테고리별 그룹핑 (최대 카테고리 4개, 각 8개)
        from collections import defaultdict
        by_cat = defaultdict(list)
        for p in raw_patterns:
            if not any(kw in p.get('rule','') for kw in ['메에스트로','부재','실패로']):
                by_cat[p['category']].append(p['rule'])
        top_cats = sorted(by_cat, key=lambda c: len(by_cat[c]), reverse=True)[:4]
        patterns_formatted = []
        for cat in top_cats:
            patterns_formatted.append({'category': cat, 'rules': by_cat[cat][:8]})
        return jsonify({
            'ok':              True,
            'judgment':        result.get('judgment', ''),
            'action':          result.get('action', ''),
            'reason':          result.get('reason', ''),
            'patterns':        patterns_formatted,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/judge', methods=['POST'])
def api_judge():
    """n8n CAiFY 워크플로우에서 호출하는 뇌 에이전트 판단 엔드포인트.
    매핑5 노드 출력값을 그대로 받아 유튜브 쇼츠 방향을 판단한다.

    Request JSON (caify_prompt 매핑 결과):
        {
            "brand_name": "한국인증센터",
            "product_name": "ESG경영, ISO인증, 경영컨설팅",
            "industry": "법인",
            "goal": "문의·상담을 늘리고 싶다.",
            "ages": "30대 / 40대 / 50대",
            "product_strengths": "전문 인력이 직접 제공한다. / 처리 속도가 빠르다.",
            "tones": "친절하게 쉽게 설명한다. / 전문가가 조언하는 느낌.",
            "action_style": "관심이 생기도록 자연스럽게 유도한다.",
            "extra_strength": "...",
            "service_types": "온라인 서비스 / 전국 서비스",
            "postLengthMode": "요약형",
            "content_styles": "짧은 문장 위주 / 핵심 요약",
            "expression": "가격·할인 언급",
            "forbidden_phrases": ""
        }

    Response JSON:
        {
            "ok": true,
            "judgment": "...",
            "reason": "...",
            "action": "...",
            "raw": "..."
        }
    """
    data = request.json or {}

    brand_name       = data.get('brand_name', '').strip()
    product_name     = data.get('product_name', '').strip()
    industry         = data.get('industry', '').strip()
    goal             = data.get('goal', '').strip()
    ages             = data.get('ages', '').strip()
    product_strengths = data.get('product_strengths', '').strip()
    extra_strength   = data.get('extra_strength', '').strip()
    tones            = data.get('tones', '').strip()
    action_style     = data.get('action_style', '').strip()
    service_types    = data.get('service_types', '').strip()
    post_length      = data.get('postLengthMode', '').strip()
    content_styles   = data.get('content_styles', '').strip()
    expression       = data.get('expression', '').strip()
    forbidden_phrases = data.get('forbidden_phrases', '').strip()

    if not brand_name or not product_name:
        return jsonify({'ok': False, 'error': 'brand_name과 product_name은 필수입니다'}), 400

    strengths_combined = ' / '.join(filter(None, [product_strengths, extra_strength]))

    situation = f"""
[고객사 정보]
브랜드명: {brand_name}
상품/서비스: {product_name}
업종: {industry}
서비스 형태: {service_types}

[마케팅 목표 & 타겟]
최우선 목표: {goal}
주요 타겟 연령대: {ages}

[강점 & 홍보 포인트]
강점: {strengths_combined}

[콘텐츠 방향 설정]
말하는 톤: {tones}
행동 유도 방식: {action_style}
콘텐츠 길이/스타일: {post_length} / {content_styles}
피해야 할 표현: {expression}
금지 문구: {forbidden_phrases}

---
위 고객사의 유튜브 쇼츠를 기획한다.
이 고객사의 잠재고객이 쇼츠를 봤을 때 흥미를 느끼고 최종적으로 전환(문의/예약/구매)까지 이어지려면
어떤 영상 구성이어야 하는가?
첫 3초 훅, 핵심 메시지, 행동 유도 방식까지 판단하라.
"""

    try:
        from agent import analyze
        result = analyze(situation)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    return jsonify({
        'ok': True,
        'judgment':         result.get('judgment', ''),
        'reason':           result.get('reason', ''),
        'action':           result.get('action', ''),
        'creative_approach': result.get('creative_approach', 'light_twist'),
        'approach_reason':  result.get('approach_reason', ''),
        'raw':              result.get('raw', '')
    })


@app.route('/api/blog_judge', methods=['POST'])
def api_blog_judge():
    """블로그 콘텐츠 전략 판단 엔드포인트 (4-step).
    매핑5 노드 출력값을 받아 키워드→전략→제목/H2를 결정한다.
    업종 불문, 오프라인이면 지역명 자동 반영.
    """
    import json as _json

    data = request.json or {}

    brand_name        = data.get('brand_name', '').strip()
    product_name      = data.get('product_name', '').strip()
    industry          = data.get('industry', '').strip()
    goal              = data.get('goal', '').strip()
    ages              = data.get('ages', '').strip()
    product_strengths = data.get('product_strengths', '').strip()
    extra_strength    = data.get('extra_strength', '').strip()
    tones             = data.get('tones', '').strip()
    action_style      = data.get('action_style', '').strip()
    service_types     = data.get('service_types', '').strip()
    expression        = data.get('expression', '').strip()
    forbidden_phrases = data.get('forbidden_phrases', '').strip()
    address           = data.get('address', '').strip()

    if not brand_name or not product_name:
        return jsonify({'ok': False, 'error': 'brand_name과 product_name은 필수입니다'}), 400

    is_offline = '오프라인' in service_types
    location_hint = f'오프라인 매장. 지역: {address}' if (is_offline and address) else '온라인/전국 서비스 (지역명 불필요)'

    situation = f"""
브랜드: {brand_name}
상품/서비스: {product_name}
업종: {industry}
서비스: {service_types} / {location_hint}
목표: {goal}
타겟 연령: {ages}
기본 강점: {product_strengths}
추가 강점(고유): {extra_strength}
톤: {tones}
유도 방식: {action_style}
피해야 할 표현: {expression}
금지 문구: {forbidden_phrases}
"""

    try:
        from agent import _get_relevant_patterns
        from openai import OpenAI
        from config_helper import get_config

        patterns_str, _ = _get_relevant_patterns(situation)
        client = OpenAI(api_key=get_config().get('openai_api_key'))

        # STEP 1: 키워드 결정
        r1 = client.chat.completions.create(
            model='gpt-4o',
            messages=[{'role': 'user', 'content': f"""
네이버 SEO 전문 마케터다. 블로그 포스팅 핵심 키워드를 결정하라.

[브랜드 정보]
{situation}

[원칙]
1. 실제 네이버 검색량 있는 롱테일 (업종+상황/절차/기간/비용/후기/차이 조합)
2. 전환 의도 높은 것 우선
3. 오프라인 매장 → 지역명+업종+서비스 조합 필수
4. 전국/온라인 → 지역명 제외, 상황/절차/기간 조합

후보 3개 뽑고 최종 1개 선택.
JSON: {{"candidates":["키워드1","키워드2","키워드3"],"selected":"최종키워드","reason":"이유"}}
"""}],
            max_tokens=300, temperature=0.2,
            response_format={'type': 'json_object'}
        )
        kw = _json.loads(r1.choices[0].message.content)
        keyword = kw.get('selected', '')

        # STEP 2: 뇌 에이전트 전략 (extra_strength 우선)
        r2 = client.chat.completions.create(
            model='gpt-4o',
            messages=[{'role': 'user', 'content': f"""
인하우스 마케터다. 아래 패턴 기반으로 블로그 전략을 결정한다.

[핵심 3축]
- Outside-In: 경쟁사가 반복하는 방향 소거. 경쟁사 안 가는 곳 + 이 브랜드 강점 교차 지점
- Asset Conversion: 강점 중 경쟁사가 말하기 가장 어려운 것 하나만 앞에 세운다
- System Thinking: 검색 → 읽기 → 전환까지 끊기지 않는 구조

[축적된 판단 패턴]
{patterns_str}

[브랜드 정보]
{situation}

[선택된 키워드]
{keyword}

[lead_strength 판단 규칙 — 순서 엄수]
1순위: 추가 강점(고유) 항목에서 먼저 찾는다. 경쟁사가 말하기 가장 어렵다.
2순위: 추가 강점에서 없을 때만 기본 강점으로 내려간다.
기준: 경쟁사 10곳 중 이걸 내세우는 곳이 적을수록 선택.

[타겟 상태 — 1개만 선택]
A. 고통 — 지금 막혀있다
B. 욕망 — 더 좋아지고 싶다
C. 비교중 — 기준 필요
D. 확신부족 — 믿음 없다

[훅 타입 — 반드시 3개 중 1개만]
역전형 / 공감형 / 욕망형

JSON: {{"target_state":"A/B/C/D","target_state_reason":"맥락","lead_strength":"강점 하나","lead_from":"extra 또는 basic","elimination":"경쟁사 반복 방향","hook_type":"역전형 또는 공감형 또는 욕망형"}}
"""}],
            max_tokens=400, temperature=0.2,
            response_format={'type': 'json_object'}
        )
        strategy = _json.loads(r2.choices[0].message.content)

        # STEP 3: 제목 + H2
        r3 = client.chat.completions.create(
            model='gpt-4o',
            messages=[{'role': 'user', 'content': f"""
네이버 블로그 제목과 H2를 만드는 마케터다.

[키워드]
{keyword}

[전략]
타겟: {strategy.get('target_state')} — {strategy.get('target_state_reason')}
앞세울 강점: {strategy.get('lead_strength')}
소거 방향: {strategy.get('elimination')}
훅 타입: {strategy.get('hook_type')}

[지역]
{location_hint}

[제목 규칙]
- 키워드가 앞 15자 안에 포함
- 오프라인이면 지역명 자연스럽게 포함
- 금지: ~하는 법, 총정리, 완벽 가이드, ~인가?, ~필수, ~중요성, ~이란, ~왜 필요
- 권장: ~했습니다, ~했어요, ~할 때, ~라면, ~차이, ~고르다, ~걸렸어요, ~받았어요

[H2 규칙]
- 키워드 검색 의도 따르되 타겟 상태+전략 구조로
- 금지: ~이란, ~중요성, ~왜 필요, ~인가, ~정의, ~총정리, 전문가의 조언
- 권장: 상황형(~할 때), 비교형(~vs~/~차이), 경험형(~했을 때), 판단형(~고르는 기준/~확인할 것)
- 앞세울 강점이 H2 하나에 자연스럽게 녹을 것
- 4~5개

JSON: {{"title":"제목","h2_titles":["H2-1","H2-2","H2-3","H2-4"],"cta_approach":"장벽 제거 방식"}}
"""}],
            max_tokens=500, temperature=0.3,
            response_format={'type': 'json_object'}
        )
        structure = _json.loads(r3.choices[0].message.content)

        # STEP 4: hook_opening — 후보 3개 후 AI 패턴 소거
        r4 = client.chat.completions.create(
            model='gpt-4o',
            messages=[{'role': 'user', 'content': f"""
블로그 첫 문단 오프닝을 만든다.

제목: {structure.get('title')}
훅 타입: {strategy.get('hook_type')}
타겟: {strategy.get('target_state')} — {strategy.get('target_state_reason')}

후보 3개 작성:
- 각 2문장
- 사람이 쓴 것처럼. AI 티 절대 없이.
- 금지: ~인가요?, ~하셨나요?, ~원하신다면, ~중요합니다, ~알아보겠습니다, 안녕하세요

3개 중 가장 자연스러운 것 1개 선택.
JSON: {{"candidates":["후보1","후보2","후보3"],"selected":"최종 2문장"}}
"""}],
            max_tokens=500, temperature=0.5,
            response_format={'type': 'json_object'}
        )
        hook_result = _json.loads(r4.choices[0].message.content)

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

    return jsonify({
        'ok':                  True,
        'keyword':             keyword,
        'keyword_candidates':  kw.get('candidates', []),
        'keyword_reason':      kw.get('reason', ''),
        'target_state':        strategy.get('target_state', ''),
        'target_state_reason': strategy.get('target_state_reason', ''),
        'lead_strength':       strategy.get('lead_strength', ''),
        'lead_from':           strategy.get('lead_from', ''),
        'elimination':         strategy.get('elimination', ''),
        'hook_type':           strategy.get('hook_type', ''),
        'title':               structure.get('title', ''),
        'h2_titles':           structure.get('h2_titles', []),
        'hook_opening':        hook_result.get('selected', ''),
        'cta_approach':        structure.get('cta_approach', '')
    })


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
        section = conv.get('section', 'marketing') or 'marketing'
        brain_reply = chat_engine.get_brain_response(conv_id, user_message, user_name, section)
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


# ── 포스팅 검토 ──────────────────────────────────────────

def _caify_api(method: str, path: str, body: dict = None) -> dict:
    """caify.ai API 호출 헬퍼"""
    import urllib.request as _req
    import urllib.error as _err
    cfg = get_config()
    base = cfg.get('caify_api_base', '').rstrip('/')
    token = cfg.get('caify_api_token', '')
    if not base:
        return {'error': 'CAIFY_API_BASE 미설정 — 설정 페이지에서 입력하세요'}
    url = f"{base}{path}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(body).encode() if body else None
    req = _req.Request(url, data=data, headers=headers, method=method)
    try:
        with _req.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except _err.HTTPError as e:
        return {'error': f'HTTP {e.code}: {e.read().decode()[:200]}'}
    except Exception as e:
        return {'error': str(e)}


@app.route('/posts')
def posts_page():
    if not session.get('is_owner'):
        return redirect(url_for('chat_start'))
    pending = db.get_pending_pattern_request_count()
    return render_template('posts.html', pending=pending)


@app.route('/api/posts/list')
def api_posts_list():
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    result = _caify_api('GET', '/admin/posts')
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']})
    posts = result if isinstance(result, list) else result.get('posts', [])
    pending_posts = [p for p in posts if p.get('status', 0) in (0, 1)]
    return jsonify({'ok': True, 'posts': pending_posts})


@app.route('/api/posts/<int:post_id>/analyze', methods=['POST'])
def api_post_analyze(post_id):
    """포스팅 LLM 분석 — SSE 스트리밍"""
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})

    from openai import OpenAI as _OAI
    data = request.json or {}
    title = data.get('title', '')
    html_content = data.get('html', '')

    cfg = get_config()
    client = _OAI(api_key=cfg.get('openai_api_key', ''))

    prompt = f"""아래 네이버 블로그 포스팅을 검토해라.

제목: {title}

본문 (HTML):
{html_content[:3000]}

다음 기준으로 평가하라:
1. **SEO** — 제목·본문 키워드 일치도, 검색 의도 부합 여부
2. **가독성** — 문장 흐름, 단락 구성, 소제목 구조
3. **설득력** — CTA 위치·강도, 독자 행동 유도
4. **종합 판단** — 발행 바로 가능 / 수정 후 발행 / 재작성 권장

간결하게 평가하고, 수정 필요 부분은 구체적으로 짚어줘."""

    def generate():
        try:
            stream = client.chat.completions.create(
                model='gpt-4o',
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=600, temperature=0.3, stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ''
                if delta:
                    yield f"data: {json.dumps({'text': delta}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/posts/<int:post_id>/chat', methods=['POST'])
def api_post_chat(post_id):
    """대화형 포스팅 수정 — SSE 스트리밍"""
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})

    from openai import OpenAI as _OAI
    data = request.json or {}
    user_message = data.get('message', '').strip()
    title        = data.get('title', '')
    current_html = data.get('html', '')
    history      = data.get('history', [])

    if not user_message:
        return jsonify({'ok': False, 'error': '메시지 없음'})

    cfg = get_config()
    client = _OAI(api_key=cfg.get('openai_api_key', ''))

    system = f"""너는 네이버 블로그 포스팅 편집자다.
현재 편집 중인 포스팅:

제목: {title}

현재 HTML:
{current_html[:3000]}

규칙:
- 수정 요청이 명확하면 수정된 HTML 전체를 ```html 코드블록으로 반환
- 의도가 불분명하면 먼저 질문
- 발행 판단 질문에는 솔직하게 평가
- 짧고 대화체로"""

    messages = [{'role': 'system', 'content': system}]
    for h in history[-6:]:
        messages.append({'role': h['role'], 'content': h['content']})
    messages.append({'role': 'user', 'content': user_message})

    def generate():
        try:
            stream = client.chat.completions.create(
                model='gpt-4o',
                messages=messages,
                max_tokens=2000, temperature=0.4, stream=True
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ''
                if delta:
                    yield f"data: {json.dumps({'text': delta}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route('/api/posts/<int:post_id>/update', methods=['POST'])
def api_post_update(post_id):
    """포스팅 내용 수정 저장"""
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    data = request.json or {}
    result = _caify_api('PATCH', f'/api/posts/{post_id}',
                        {'title': data.get('title'), 'html': data.get('html')})
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']})
    return jsonify({'ok': True})


@app.route('/api/posts/<int:post_id>/approve', methods=['POST'])
def api_post_approve(post_id):
    """발행 승인 — status → 1 (Flutter/Electron이 자동 발행)"""
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    result = _caify_api('POST', f'/admin/posts/{post_id}/approve')
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']})
    return jsonify({'ok': True})


@app.route('/api/posts/<int:post_id>/reject', methods=['POST'])
def api_post_reject(post_id):
    """포스팅 반려"""
    if not session.get('is_owner'):
        return jsonify({'ok': False, 'error': '권한 없음'})
    result = _caify_api('POST', f'/api/posts/{post_id}/reject')
    if 'error' in result:
        return jsonify({'ok': False, 'error': result['error']})
    return jsonify({'ok': True})


# ── MCP 서버 (Claude.ai 웹 연동) ────────────────────────

_mcp_sessions: dict = {}  # {session_id: Queue}

_MCP_TOOLS = [
    {
        'name': 'search_brain_patterns',
        'description': (
            '마케팅 상황과 관련된 뇌 에이전트의 판단 패턴을 검색합니다. '
            '1,180개 패턴 중 입력한 상황과 가장 유사한 패턴 50개를 반환합니다. '
            '전략 수립, 채널 판단, 타겟 설정 등 마케팅 의사결정에 활용하세요.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': '검색할 마케팅 상황이나 고민'}
            },
            'required': ['query']
        }
    },
    {
        'name': 'get_brain_judgment',
        'description': (
            '특정 상황에 대한 뇌 에이전트의 직접 판단을 받습니다. '
            '유튜브 쇼츠 콘텐츠 방향, 마케팅 전략, 포지셔닝 판단에 특화되어 있습니다. '
            '공간명, 업종, 강점, 타겟, 목표를 포함해서 요청하면 더 구체적인 판단이 나옵니다.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'situation': {'type': 'string', 'description': '판단받을 상황 설명 (업종, 강점, 타겟, 목표 포함 권장)'}
            },
            'required': ['situation']
        }
    }
]


def _mcp_handle(method, params, msg_id):
    if method == 'initialize':
        return {
            'jsonrpc': '2.0', 'id': msg_id,
            'result': {
                'protocolVersion': '2024-11-05',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': '뇌-에이전트', 'version': '1.0'}
            }
        }
    elif method in ('notifications/initialized', 'ping'):
        return None
    elif method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': msg_id, 'result': {'tools': _MCP_TOOLS}}
    elif method == 'tools/call':
        tool = params.get('name')
        args = params.get('arguments', {})
        try:
            if tool == 'search_brain_patterns':
                import embeddings
                patterns = embeddings.search_patterns(args['query'], top_k=50)
                by_cat: dict = {}
                for p in patterns:
                    by_cat.setdefault(p['category'], []).append(p['rule'])
                lines = []
                for cat, rules in by_cat.items():
                    lines.append(f"[{cat}]")
                    for r in rules:
                        lines.append(f"  - {r}")
                text = "\n".join(lines) if lines else "관련 패턴 없음"
            elif tool == 'get_brain_judgment':
                from agent import analyze
                text = analyze(args['situation'])
            else:
                text = f"알 수 없는 도구: {tool}"
            return {'jsonrpc': '2.0', 'id': msg_id,
                    'result': {'content': [{'type': 'text', 'text': text}]}}
        except Exception as e:
            return {'jsonrpc': '2.0', 'id': msg_id,
                    'error': {'code': -32000, 'message': str(e)}}
    return {'jsonrpc': '2.0', 'id': msg_id, 'result': {}}


@app.route('/video-cases')
def video_cases():
    cases = db.get_approved_video_cases()
    counts = db.get_video_case_counts()
    return render_template('video_cases.html', cases=cases, counts=counts)


@app.route('/api/video-cases/delete/<int:case_id>', methods=['POST'])
def api_delete_video_case(case_id):
    db.reject_video_case(case_id)
    return jsonify({'status': 'ok'})


@app.route('/video-simulations')
def video_simulations():
    sims = db.get_video_simulations(limit=50)
    counts = db.get_video_simulation_counts()
    return render_template('video_simulations.html', sims=sims, counts=counts)


@app.route('/api/video-simulations/promote/<int:sim_id>', methods=['POST'])
def api_promote_video_simulation(sim_id):
    case_id = db.promote_video_simulation(sim_id)
    return jsonify({'status': 'ok', 'case_id': case_id})


@app.route('/api/video-simulations/dismiss/<int:sim_id>', methods=['POST'])
def api_dismiss_video_simulation(sim_id):
    db.dismiss_video_simulation(sim_id)
    return jsonify({'status': 'ok'})


@app.route('/api/video-simulations/run', methods=['POST'])
def api_run_video_simulation():
    """즉시 영상 시뮬레이션 1건 실행 (랜덤 또는 커스텀 브랜드)"""
    data = request.json or {}
    brand = data.get('brand') or None  # None이면 랜덤
    try:
        result = video_simulator.run_video_simulation(brand=brand)
        if 'error' in result:
            return jsonify({'status': 'error', 'message': result['error']}), 500
        return jsonify({'status': 'ok', 'id': result.get('id')})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/video-simulations/feedback/<int:sim_id>', methods=['POST'])
def api_video_simulation_feedback(sim_id):
    """시뮬레이션 결과에 '나라면 이렇게' 피드백 → 케이스로 저장"""
    data = request.json or {}
    feedback = data.get('feedback', '').strip()
    if not feedback:
        return jsonify({'error': '피드백 내용이 없습니다'}), 400

    sims = db.get_video_simulations(limit=200)
    sim = next((s for s in sims if s['id'] == sim_id), None)
    if not sim:
        return jsonify({'error': '시뮬레이션을 찾을 수 없습니다'}), 404

    brand = sim.get('brand', {})
    brand_info = video_simulator.situation_text(brand)

    from agent import extract_video_case_from_feedback
    safe_brand = brand_info.encode('utf-8', errors='ignore').decode('utf-8')
    safe_feedback = feedback.encode('utf-8', errors='ignore').decode('utf-8')
    result = extract_video_case_from_feedback(safe_feedback, safe_brand)

    if 'error' in result:
        return jsonify({'status': 'error', 'message': result['error']}), 500
    return jsonify({'status': 'ok', 'case_id': result.get('id'),
                    'industry': result.get('industry'), 'plan': result.get('plan')})


@app.route('/robots.txt')
def robots_txt():
    return Response('User-agent: *\nAllow: /\n', mimetype='text/plain')


@app.route('/mcp/sse')
def mcp_sse():
    session_id = str(uuid.uuid4())
    q = queue.Queue()
    _mcp_sessions[session_id] = q

    def generate():
        msg_url = f"/mcp/message?session_id={session_id}"
        yield f"event: endpoint\ndata: {json.dumps(msg_url)}\n\n"
        try:
            while True:
                try:
                    item = q.get(timeout=25)
                    if item is None:
                        break
                    yield f"event: message\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            _mcp_sessions.pop(session_id, None)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@app.route('/mcp/message', methods=['POST'])
def mcp_message():
    session_id = request.args.get('session_id', '')
    if session_id not in _mcp_sessions:
        return jsonify({'error': 'session not found'}), 400
    msg = request.json or {}
    result = _mcp_handle(msg.get('method', ''), msg.get('params', {}), msg.get('id'))
    if result is not None:
        _mcp_sessions[session_id].put(result)
    return '', 202


# ── 유틸 ─────────────────────────────────────────────────

def _reschedule(sim_hour):
    try:
        scheduler.reschedule_job('daily_sim', trigger='cron', hour=sim_hour, minute=0)
    except Exception:
        pass


# ── 메인 ─────────────────────────────────────────────────

if __name__ == '__main__':
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
