# -*- coding: utf-8 -*-
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from openai import OpenAI
import db

BASE_DIR = Path(__file__).parent
PATTERNS_PATH = BASE_DIR / "brain" / "patterns.json"
REAL_CASES_PATH = BASE_DIR / "brain" / "real_cases.json"
from config_helper import get_config

# 이 에이전트의 고유 사고 프레임워크 — 모든 분석의 기준
BRAIN_FRAMEWORK_STR = """
[이 에이전트의 사고 프레임워크 — 반드시 이 언어로 분석해라]

핵심 3축:
- 외부 우선 (Outside-In): 판단의 시작은 항상 외부. 경쟁사/시장/환경부터 본다. 내부 문제로 단정하기 전에 외부 요인을 먼저 소거한다.
- 자산 전환 (Asset Conversion): 새로 만들기 전에 이미 가진 것의 전환 가능성을 먼저 본다. 기존 고객, DB, 팔로워, 후기, 파트너십이 먼저다.
- 구조 설계 (System Thinking): 단발 이벤트가 아닌 반복되는 구조를 만든다. 한 번 설계하면 계속 굴러가는 구조인지 확인한다.

고유 사고 시그니처 5가지:
① 판 바꾸기: 약점이 있을 때 보완하지 않는다. 경쟁 축 자체를 바꾼다.
② 타겟 착시 간파: 타겟 인구통계가 겹쳐도 구매 의도(intent)가 다르면 전환 안 된다.
③ 증명 우선: 말로 설명하지 않고 이벤트/수치로 증명한다.
④ 레버리지 연결: 확정된 것을 미확정 협상의 레버리지로 활용한다. 빈손으로 협상 가지 않는다.
⑤ 수치 타겟화: 막연한 그룹이 아니라 비율/수치로 타겟을 구체화한다.

분석 출력 기준:
- what_agent_missed는 이 프레임워크 언어로 표현해라
  예: "Outside-In 적용 미흡 — 규제 변화를 먼저 외부 체크했어야 함"
  예: "Asset Conversion 기회 놓침 — 기존 고객 DB가 있는데 새 채널부터 탐색함"
  예: "System Thinking 부재 — 단발 이벤트로 기획했지만 구조화 가능한 상황이었음"
- new_patterns는 이 프레임워크가 새 상황에서 어떻게 확장되는지를 표현해라
  예: "규제 환경도 Outside-In 원칙 적용 대상 — 이미 통과한 파트너를 Asset으로 전환하라"
  예: "판 바꾸기 시그니처의 확장 — 약점을 숨기는 것이 아니라 그 약점이 강점이 되는 맥락을 만들어라"
"""

_industry_pool = []  # 셔플된 순환 풀

def _pick_industry(industries):
    global _industry_pool
    if not _industry_pool:
        _industry_pool = industries[:]
        random.shuffle(_industry_pool)
    return _industry_pool.pop()

INDUSTRIES = [
    "1인 세무/회계 컨설팅", "소규모 카페/디저트 매장", "B2B SaaS 스타트업",
    "건강기능식품 이커머스", "개인 PT 헬스장", "온라인 교육 플랫폼",
    "인테리어/리모델링 업체", "모바일 앱 서비스 (B2C)", "피부과/한의원 클리닉",
    "HR/채용 서비스", "패션/뷰티 이커머스", "소프트웨어 개발 에이전시",
    "로컬 청소/생활 서비스", "미디어/뉴스레터 스타트업", "펫 케어 서비스",
    "중소 제조업체 (OEM/ODM)", "부동산 중개/컨설팅", "이벤트/웨딩 플래닝",
    "자동차 관련 서비스", "ESG/지속가능경영 컨설팅"
]

CHALLENGES = [
    "유입은 있는데 전환율이 낮음",
    "신규 런칭 후 초기 고객 확보 필요",
    "기존 고객 재구매율이 15% 이하",
    "소개 채널이 막히면서 신규 수주 채널 필요",
    "브랜드 인지도 0에서 시작하는 상황",
    "광고비 대비 ROAS가 안 나옴",
    "B2B 영업 사이클이 너무 길어 현금흐름 문제",
    "앱/서비스 가입 후 이탈률 높음",
    "콘텐츠는 많은데 실제 문의로 연결 안 됨",
    "경쟁사 대비 가격 경쟁력이 약한 상황",
    "3개월 이상 매출 정체",
    "팔로워/구독자는 많은데 실제 매출 연결이 안 됨",
    "신제품 출시 후 기존 고객에게 알리는 방법",
    "예산 월 30만원 이하로 성장해야 하는 상황"
]


def get_client():
    api_key = get_config().get('openai_api_key', '')
    if not api_key:
        raise ValueError("OpenAI API 키가 설정되지 않았습니다. 설정 페이지에서 입력해주세요.")
    return OpenAI(api_key=api_key)


def generate_scenario():
    client = get_client()
    industry = _pick_industry(INDUSTRIES)
    challenge = random.choice(CHALLENGES)

    prompt = f"""실제 같은 마케팅/전략 시나리오를 하나 생성해라.

업종: {industry}
핵심 과제: {challenge}

아래 JSON 형식으로만 출력해라:
{{
  "industry": "구체적인 업종명",
  "company_size": "1인 / 소규모(5명 이하) / 중소(10-50명) 중 하나",
  "challenge": "핵심 과제 한 줄",
  "context": "상황 설명 (현실적이고 구체적으로, 3-4문장. 수치 포함)",
  "goal": "달성하고 싶은 목표 (수치 포함)",
  "assets": "현재 보유 자산 (고객 수, DB, 팔로워, 예산 등 구체적으로)",
  "constraints": "제약 조건 (예산, 인력, 시간 등)"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9,
        max_tokens=600,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


def evaluate_with_brain(scenario):
    client = get_client()
    patterns_data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))

    patterns_str = "\n".join([
        f"[{p['id']}] ({p['category']}) {p['rule']}"
        for p in patterns_data['patterns']
    ])
    axes_str = "\n".join([
        f"- {a['name']}: {a['description']}"
        for a in patterns_data['axes']
    ])

    prompt = f"""너는 아래 사고 패턴을 가진 마케터다. 반드시 이 패턴들만으로 판단해라. 일반적인 마케팅 상식으로 판단하지 마라.

[3개 핵심 축]
{axes_str}

[고유 사고 시그니처 5가지 — 판단 전 반드시 체크]
① 판 바꾸기: 약점 보완 말고, 경쟁 축 자체를 바꿀 방법이 있는가?
② 타겟 착시 간파: 타겟이 겹쳐 보여도 구매 의도가 다를 수 있다. 진짜 의도 확인했는가?
③ 증명 우선: 말로 설명하는 액션은 탈락. 수치/이벤트/구조로 증명하는 방식인가?
④ 레버리지 연결: 확정된 자산/계약/관계를 협상 도구로 쓸 수 있는가?
⑤ 수치 타겟화: "고객군" 아닌 비율/수치로 타겟을 잘라냈는가?

[판단 패턴 목록]
{patterns_str}

[시나리오]
업종: {scenario.get('industry')} ({scenario.get('company_size')})
상황: {scenario.get('context')}
목표: {scenario.get('goal')}
보유 자산: {scenario.get('assets')}
제약: {scenario.get('constraints')}

[액션 작성 필수 기준 — 어기면 틀린 판단]
- 각 액션에 구체적 수치 또는 측정 기준 포함 (예: "DB 상위 20% 이탈 고객 500명 직접 연락" O / "고객에게 마케팅 진행" X)
- "파트너십 구축", "마케팅 캠페인 진행", "고객 경험 개선" 같은 일반 문구 금지
- 판 바꾸기 가능성 먼저 검토 후 결론 내릴 것
- 말로 설명하는 액션 금지 — 수치/이벤트/구조로 증명하는 방식으로만

gaps 작성 기준:
- 패턴 목록이 명확한 답을 못 주는 상황
- 패턴 충돌 또는 모호한 상황
- 업종 특수성으로 패턴이 그대로 적용 안 되는 부분
- 직감으로 때운 부분
위 중 하나라도 해당하면 반드시 포함.

confidence 기준:
- 모든 판단에 패턴 근거 명확하면 80+
- 일부 직감으로 때운 부분 있으면 60-79
- 패턴 공백이 핵심 판단에 영향 주면 60 미만

JSON 형식으로만 출력:
{{
  "judgment": "핵심 판단 결론 (1-2문장, 구체적 방향 포함)",
  "action": "지금 당장 할 것 3가지 (반드시 수치/구체적 방식 포함)",
  "reasoning": "어떤 패턴과 시그니처가 왜 발동됐는지 (2-3문장)",
  "patterns_fired": [발동된 패턴 ID 정수 목록],
  "gaps": ["패턴으로 커버 안 된 구체적인 판단 상황"],
  "confidence": 0에서 100 사이 정수,
  "flag_for_review": true 또는 false
}}

신뢰도 70 미만이거나 gaps가 1개 이상이면 flag_for_review = true"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=800,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


def _is_valid_pattern(rule: str) -> bool:
    """패턴 품질 필터 — 사례 설명/범용 조언 차단, 조건부 원칙만 허용"""
    if not rule or len(rule) < 15:
        return False
    # 사례 설명형 차단
    case_desc = ['에이전트는', '했으나', '했지만', '않았다', '못했다', '놓쳤다', '집중했다']
    if any(m in rule for m in case_desc):
        return False
    # 범용 LLM 조언 차단
    bad_endings = ['할 수 있다', '가능하다', '효과적이다', '필요하다', '고려하라', '강화하라',
                   '확보할 수 있다', '높일 수 있다', '제공할 수 있다', '기여할 수 있다',
                   '활용할 수 있다', '작용할 수 있다', '도모할 수 있다', '수 있으며']
    if any(rule.endswith(e) for e in bad_endings):
        return False
    # → 없으면 경고 수준 (통과시키되 화살표 없는 건 약한 패턴)
    return True


def auto_grow_from_gap(scenario, result):
    """갭에서 새 패턴을 자동 도출해 즉시 추가 — 신뢰도 75 이상만"""
    gaps = result.get('gaps', [])
    if not gaps:
        return []

    client = get_client()
    patterns_data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))
    existing_rules = [p['rule'] for p in patterns_data['patterns']]
    existing_str = "\n".join(existing_rules)

    scenario_str = f"""업종: {scenario.get('industry')} ({scenario.get('company_size', '')})
과제: {scenario.get('challenge')}
상황: {scenario.get('context')}
목표: {scenario.get('goal')}
보유 자산: {scenario.get('assets')}
제약: {scenario.get('constraints')}"""

    gaps_str = "\n".join(f"- {g}" for g in gaps)

    prompt = f"""{BRAIN_FRAMEWORK_STR}

마케팅 전략 판단 중에 기존 패턴으로 커버되지 않은 공백이 발견됐다.
이 공백에서 이 에이전트의 사고 프레임워크가 확장되는 새로운 판단 패턴을 도출해라.

[시나리오]
{scenario_str}

[발견된 공백]
{gaps_str}

[기존 패턴 목록 — 이와 다른 것만 도출]
{existing_str}

패턴 작성 규칙 — 반드시 지켜라:
1. 형식: "조건/상황 → 판단 원칙" (→ 필수)
   예시 O: "경쟁사가 가격으로 싸우는 상황 + 우리가 수치로 증명 가능한 강점 있을 때 → 가격 경쟁 탈출, 증명 우선으로 판 바꾸기"
   예시 X: "판 바꾸기를 고려할 수 있다" (→ 없음, 조건 없음, 금지)
   예시 X: "에이전트는 판 바꾸기를 하지 않았다" (사례 설명, 금지)
2. "~할 수 있다", "~효과적이다", "~고려하라" 로 끝나는 패턴 금지
3. 이 케이스에서만 해당하는 것 금지 — 다른 업종에도 적용 가능한 조건부 원칙이어야 함
4. 신뢰도 80 미만이면 도출하지 마라

카테고리는 다음 중 하나: 채널 판단 / 전환 판단 / 자산 활용 / 구조/전략 판단 / 런칭/가격 판단 / 파트너십 판단 / 실행/의사결정 메타

JSON 형식으로만 출력:
{{
  "new_patterns": [
    {{"category": "카테고리명", "rule": "조건 → 판단 원칙", "confidence": 0에서 100 사이 정수}}
  ]
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=800,
        response_format={"type": "json_object"}
    )
    data = json.loads(response.choices[0].message.content)
    added = []
    for p in data.get('new_patterns', []):
        rule = p.get('rule', '').strip()
        if p.get('confidence', 0) >= 80 and _is_valid_pattern(rule):
            new_id = db.add_pattern(p['category'], rule)
            added.append({'id': new_id, 'category': p['category'], 'rule': rule, 'confidence': p['confidence']})
    return added


def auto_synthesize_and_apply():
    """합성 실행 후 고신뢰도 새 패턴 자동 추가"""
    try:
        result = synthesize_patterns()
        added = []
        for p in result.get('new_patterns_from_gaps', []):
            new_id = db.add_pattern(p.get('category', '기타'), p['rule'])
            added.append(new_id)
        return added
    except Exception:
        return []


def run_simulation():
    # 누적 시뮬 수 확인해서 스트레스 시나리오 비율 조절
    stats = db.get_dashboard_stats()
    total = stats.get('total_simulations', 0)

    # 초기엔 일반 랜덤, 5회 이상부터 스트레스 시나리오 50%
    if total >= 5 and random.random() < 0.6:
        scenario = generate_stress_scenario()
    else:
        scenario = generate_scenario()

    result = evaluate_with_brain(scenario)
    db.save_simulation(
        scenario=scenario,
        response=result,
        patterns_fired=result.get('patterns_fired', []),
        gaps=result.get('gaps', []),
        confidence=result.get('confidence', 0),
        flagged=result.get('flag_for_review', False)
    )

    # 갭 있으면 자동 패턴 추가
    auto_added = []
    if result.get('gaps'):
        auto_added = auto_grow_from_gap(scenario, result)

    # 10회마다 자동 합성
    new_total = total + 1
    if new_total % 10 == 0:
        auto_synthesize_and_apply()

    return scenario, result, auto_added


def generate_stress_scenario():
    """잘 안 쓰이는 패턴과 반복된 갭을 타겟팅하는 도전적 시나리오 생성"""
    client = get_client()
    patterns_data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))

    fire_count = db.get_pattern_fire_counts(30)
    all_patterns = patterns_data['patterns']

    # 발동 횟수 낮은 패턴 우선 타겟
    weak = sorted(all_patterns, key=lambda p: fire_count.get(p['id'], 0))
    target = random.sample(weak[:max(3, len(weak)//2)], min(3, len(weak)))

    gaps = db.get_recurring_gaps(5)

    patterns_str = "\n".join([f"[{p['id']}] {p['rule']}" for p in target])
    gaps_str = "\n".join(gaps) if gaps else "없음"

    prompt = f"""현실적인 마케팅/전략 시나리오를 생성해라.
단순히 패턴이 맞아떨어지는 쉬운 케이스가 아니라, 아래 패턴들이 실제로 도전받고
기존 패턴만으로 판단이 불완전한 복합 상황이어야 한다.

[도전할 패턴들 — 이 패턴이 적용되지만 쉽지 않은 상황]
{patterns_str}

[반복된 패턴 공백 — 이 영역도 포함]
{gaps_str}

JSON 형식으로만 출력:
{{
  "industry": "구체적 업종명",
  "company_size": "1인 / 소규모(5명 이하) / 중소(10-50명) 중 하나",
  "challenge": "핵심 과제 한 줄",
  "context": "상황 설명 (3-4문장, 수치 포함, 패턴 적용이 까다로운 복합 상황)",
  "goal": "달성 목표",
  "assets": "보유 자산 (구체적 수치)",
  "constraints": "제약 조건",
  "stress_point": "기존 패턴만으로 판단이 어려운 이유"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.95,
        max_tokens=700,
        response_format={"type": "json_object"}
    )
    result = json.loads(response.choices[0].message.content)
    result['_target_pattern_ids'] = [p['id'] for p in target]
    result['_mode'] = 'stress'
    return result


def evaluate_user_response(scenario, user_response):
    """유저 판단을 패턴 기준으로 평가 — 적용된 것, 빠진 것, 새 통찰, 확장 각도"""
    client = get_client()
    patterns_data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))

    patterns_str = "\n".join([
        f"[{p['id']}] ({p['category']}) {p['rule']}"
        for p in patterns_data['patterns']
    ])
    axes_str = "\n".join([f"- {a['name']}: {a['description']}" for a in patterns_data['axes']])

    scenario_str = f"""업종: {scenario.get('industry')} ({scenario.get('company_size', '')})
과제: {scenario.get('challenge')}
상황: {scenario.get('context')}
목표: {scenario.get('goal')}
보유 자산: {scenario.get('assets')}
제약: {scenario.get('constraints')}"""

    prompt = f"""너는 이 마케터의 사고 코치다.
마케터의 판단을 기존 패턴 목록과 정밀하게 대조 분석해라.

[핵심 3축]
{axes_str}

[기존 패턴 목록]
{patterns_str}

[시나리오]
{scenario_str}

[마케터의 실제 판단]
{user_response}

분석 지침:
- 패턴과 정확히 대응시켜라. 애매하면 부분 적용으로 표시
- 빠진 패턴은 이 케이스에서 왜 결정적인지 구체적으로 설명
- 새로운 사고 원칙은 기존 패턴과 명확히 다른 것만 추출
- 확장 각도는 이 마케터 사고 스타일(외부우선/자산전환/구조설계)에 맞게

JSON 형식으로만 출력:
{{
  "applied_correctly": [{{"pattern_id": 정수, "reason": "왜 잘 적용됐는지"}}],
  "missed_patterns": [{{"pattern_id": 정수, "what_was_missed": "구체적으로 뭘 놓쳤는지", "why_matters": "이 케이스에서 왜 결정적인지"}}],
  "new_insights": ["기존 패턴에 없는 새로운 원칙 (패턴 형태로 작성)"],
  "expansion_angles": ["이 사고를 더 발전시킬 수 있는 구체적 각도"],
  "overall_score": 0에서 100 사이 정수,
  "summary": "이 판단의 강점과 핵심 성장 방향 2-3문장"
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1500,
        response_format={"type": "json_object"}
    )
    result = json.loads(response.choices[0].message.content)
    db.save_training_session(scenario, user_response, result)
    return result


def synthesize_patterns():
    """누적 패턴 분석 — 중복 합성, 사각지대 발견, 상위 원칙 도출"""
    client = get_client()
    patterns_data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))

    fire_count = db.get_pattern_fire_counts(50)
    patterns_with_stats = [
        {**p, 'fire_count': fire_count.get(p['id'], 0)}
        for p in patterns_data['patterns']
    ]

    patterns_str = "\n".join([
        f"[{p['id']}] ({p['category']}, 발동:{p['fire_count']}회) {p['rule']}"
        for p in patterns_with_stats
    ])
    gaps_str = "\n".join(db.get_recurring_gaps(10)) or "없음"

    prompt = f"""아래 패턴 목록을 분석해서 성장 합성 리포트를 만들어라.

[패턴 목록 (발동 횟수 포함)]
{patterns_str}

[반복된 패턴 공백]
{gaps_str}

JSON 형식으로만 출력:
{{
  "duplicates": [{{"ids": [정수, 정수], "reason": "겹치는 이유", "merged_rule": "합친 새 패턴"}}],
  "dead_patterns": [{{"id": 정수, "reason": "안 쓰이는 이유", "suggestion": "수정 방향 또는 삭제 제안"}}],
  "new_patterns_from_gaps": [{{"category": "카테고리명", "rule": "새 패턴 내용", "from_gap": "어떤 공백에서 도출됐는지"}}],
  "meta_patterns": [{{"rule": "여러 패턴에서 보이는 상위 원칙", "derived_from_ids": [정수]}}]
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2000,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


def get_unrun_real_cases(n=1):
    """미실행 사례 n개 반환. 부족하면 새로 생성해서 채움."""
    cases_data = json.loads(REAL_CASES_PATH.read_text(encoding='utf-8'))
    run_ids = db.get_run_real_case_ids()
    unrun = [c for c in cases_data['cases'] if c['id'] not in run_ids]

    # 미실행 사례가 n개보다 부족하면 먼저 새 사례 생성
    if len(unrun) < n:
        try:
            generate_new_cases(10)
            # 새로 읽어서 다시 필터
            cases_data = json.loads(REAL_CASES_PATH.read_text(encoding='utf-8'))
            unrun = [c for c in cases_data['cases'] if c['id'] not in run_ids]
        except Exception:
            pass

    return random.sample(unrun, min(n, len(unrun)))


def count_unrun_real_cases():
    cases_data = json.loads(REAL_CASES_PATH.read_text(encoding='utf-8'))
    run_ids = db.get_run_real_case_ids()
    return len([c for c in cases_data['cases'] if c['id'] not in run_ids])


def generate_new_cases(n=10):
    """GPT 지식 기반으로 새 실제 사례 생성 후 real_cases.json에 추가"""
    client = get_client()
    cases_data = json.loads(REAL_CASES_PATH.read_text(encoding='utf-8'))
    existing_companies = [c.get('company', '') for c in cases_data['cases']]
    existing_str = ", ".join(existing_companies)
    max_id = max(c['id'] for c in cases_data['cases'])

    prompt = f"""한국 실제 기업의 마케팅/전략 케이스 {n}개를 생성해라.

이미 있는 사례 (중복 금지): {existing_str}

[케이스 구성 조건 — 반드시 지켜라]
- 중소기업/스타트업/소상공인: 6개 이상 (대기업 2개 이하)
- 해외 진출 케이스: 1개 이하 (국내 내수 시장 중심)
- 성공 6개 : 실패 4개 비율 (실패 케이스 충분히 포함)
- 실제 일어난 일 (실제 기업, 실제 결과, 실제 수치)
- context에 실제 결정/결과 포함하지 말 것

[아래 상황 유형 반드시 포함 — 시그니처 테스트용]
① 약점이 있고 경쟁이 치열한 상황 (판 바꾸기 필요)
② 재구매율/이탈률/전환율 수치가 있는 상황 (수치 타겟화 필요)
③ 신뢰 부족 또는 검증 안 된 제품 상황 (증명 우선 필요)
④ 기존 자산/계약/관계가 있는 협상 상황 (레버리지 연결 필요)
⑤ 타겟이 겹쳐 보이지만 실제 구매 의도가 다를 수 있는 상황 (타겟 착시 필요)

JSON 형식으로만 출력:
{{
  "cases": [
    {{
      "company": "회사명",
      "industry": "구체적 업종명",
      "company_size": "1인 / 소규모(5명 이하) / 중소(10-50명) 중 하나",
      "challenge": "핵심 과제 한 줄",
      "context": "상황 설명 3-4문장 (수치 포함, 실제 결정·결과는 포함하지 말 것)",
      "goal": "달성 목표 (수치 포함)",
      "assets": "보유 자산 (구체적)",
      "constraints": "제약 조건",
      "actual_decision": "실제로 한 결정",
      "actual_result": "실제 결과 (수치 포함)",
      "outcome": "success 또는 failure",
      "key_insight": "이 케이스의 핵심 학습 포인트 1-2문장",
      "type": "real"
    }}
  ]
}}"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=4000,
        response_format={"type": "json_object"}
    )
    new_cases = json.loads(response.choices[0].message.content).get('cases', [])

    for i, case in enumerate(new_cases):
        case['id'] = max_id + i + 1

    cases_data['cases'].extend(new_cases)
    cases_data['updated_at'] = date.today().isoformat()
    REAL_CASES_PATH.write_text(json.dumps(cases_data, ensure_ascii=False, indent=2), encoding='utf-8')

    return new_cases


def compare_judgment_to_outcome(scenario, agent_judgment, actual_outcome):
    client = get_client()
    patterns_data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))
    existing_rules = [p['rule'] for p in patterns_data['patterns']]
    existing_str = "\n".join(existing_rules[:60])  # 토큰 절약, 대표 패턴만

    scenario_str = f"""업종: {scenario.get('industry')} ({scenario.get('company_size', '')})
과제: {scenario.get('challenge')}
상황: {scenario.get('context')}
목표: {scenario.get('goal')}
보유 자산: {scenario.get('assets')}
제약: {scenario.get('constraints')}"""

    prompt = f"""{BRAIN_FRAMEWORK_STR}

[기존 패턴 목록 — 이미 있는 것과 다른 new_patterns만 도출]
{existing_str}

마케팅 전략 판단과 실제 결과를 대조 분석해라.

[시나리오]
{scenario_str}

[에이전트 판단]
판단: {agent_judgment.get('judgment')}
실행 제안: {agent_judgment.get('action')}
근거: {agent_judgment.get('reasoning')}

[실제로 일어난 일]
실제 결정: {actual_outcome.get('decision')}
실제 결과: {actual_outcome.get('result')}
성패: {actual_outcome.get('outcome')}
핵심 인사이트: {actual_outcome.get('key_insight')}

분석 기준:
- match_score: 에이전트 판단 방향이 실제 성공 방향과 얼마나 일치하는가 (0~100)
- aligned: match_score 70 이상이고 실제 outcome이 success인 경우 true
- what_agent_got_right: 실제 결과와 방향 일치한 판단들 — "무엇을 어떻게 잘 했는지" 구체적으로
- what_agent_missed: 시그니처 5개 각각 체크 후 실제로 해당하는 것만 포함

[what_agent_missed 작성 기준 — 엄격하게]
레이블만 붙이지 마라. "Outside-In 적용 미흡"으로 끝내지 말고
"이 상황에서 [구체적 외부 요인 X]를 먼저 봤어야 했는데, 에이전트는 [Y]를 했다" 형태로 써라.

5개 시그니처 체크:
① 판 바꾸기: 에이전트가 약점 보완 방식으로 갔는데 경쟁 축을 바꿀 기회가 있었는가?
② 타겟 착시: 에이전트가 잡은 타겟이 실제 구매 의도와 달랐는가?
③ 증명 우선: 에이전트가 말/캠페인으로 설명했는데 수치/이벤트/구조로 증명할 수 있었는가?
④ 레버리지 연결: 확정된 자산이 있었는데 협상 도구로 쓰지 않았는가?
⑤ 수치 타겟화: 타겟을 막연하게 잡았는데 구체적 수치로 잘라낼 수 있었는가?
→ 해당하는 것만 포함. 해당 없으면 그 항목 빼라. 억지로 채우지 마라.

JSON 형식으로만 출력:
{{
  "match_score": 0에서 100 사이 정수,
  "aligned": true 또는 false,
  "what_agent_got_right": ["구체적으로 무엇을 어떻게 잘 판단했는지"],
  "what_agent_missed": ["구체적 상황 + 어떤 시그니처가 왜 필요했는지 — 레이블만 금지"],
  "why_actual_worked": "실제 결정이 왜 성공/실패했는지 — 이 프레임워크의 어떤 원칙이 작동/미작동했는지",
  "new_patterns": [
    {{"category": "카테고리명", "rule": "조건/상황 → 판단 원칙 (→ 필수, 다른 업종에도 적용 가능한 조건부 원칙)", "confidence": 0에서 100 사이 정수}}
  ],
  "summary": "이 케이스에서 이 에이전트가 실제로 성장한 것 vs 아직 부족한 것 — 2-3문장"
}}

new_patterns 작성 규칙:
- 형식: "조건 → 판단 원칙" (→ 반드시 포함)
- "~할 수 있다", "~효과적이다", "~고려하라", "에이전트는 ~했다" 형태 금지
- 이 케이스 특수 상황 금지 — 다른 업종/상황에도 일반화 가능한 것만
- confidence 80 미만 도출 금지
카테고리는 다음 중 하나: 채널 판단 / 전환 판단 / 자산 활용 / 구조/전략 판단 / 런칭/가격 판단 / 파트너십 판단 / 실행/의사결정 메타"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1200,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


def run_one_real_case(case):
    """케이스 하나 실행 — 내부 공통 로직"""
    scenario = {
        'industry': case['industry'],
        'company_size': case['company_size'],
        'challenge': case['challenge'],
        'context': case['context'],
        'goal': case['goal'],
        'assets': case['assets'],
        'constraints': case['constraints']
    }

    agent_judgment = evaluate_with_brain(scenario)

    actual_outcome = {
        'decision': case['actual_decision'],
        'result': case['actual_result'],
        'outcome': case['outcome'],
        'key_insight': case['key_insight']
    }

    comparison = compare_judgment_to_outcome(scenario, agent_judgment, actual_outcome)

    match_score = comparison.get('match_score', 0)
    aligned = comparison.get('aligned', False)

    auto_added = []
    if aligned and case['outcome'] == 'success':
        for p in comparison.get('new_patterns', []):
            rule = p.get('rule', '').strip()
            if p.get('confidence', 0) >= 80 and _is_valid_pattern(rule):
                new_id = db.add_pattern(p['category'], rule)
                auto_added.append({'id': new_id, 'category': p['category'], 'rule': rule})

    flagged = not aligned or case['outcome'] == 'failure'

    db.save_real_case_simulation(
        case_id=case['id'],
        company=case.get('company', ''),
        scenario=scenario,
        agent_judgment=agent_judgment,
        actual_outcome=actual_outcome,
        comparison=comparison,
        match_score=match_score,
        aligned=aligned,
        patterns_fired=agent_judgment.get('patterns_fired', []),
        new_patterns_added=[p['id'] for p in auto_added],
        flagged=flagged
    )

    return {
        'company': case.get('company', ''),
        'industry': scenario['industry'],
        'match_score': match_score,
        'aligned': aligned,
        'outcome': case['outcome'],
        'auto_added': len(auto_added),
        'new_pattern_rules': [p['rule'] for p in auto_added],
        'flagged': flagged,
        # 상세 데이터
        'judgment': agent_judgment.get('judgment', ''),
        'action': agent_judgment.get('action', ''),
        'reasoning': agent_judgment.get('reasoning', ''),
        'got_right': comparison.get('what_agent_got_right', []),
        'missed': comparison.get('what_agent_missed', []),
        'actual_decision': actual_outcome.get('decision', ''),
        'actual_result': actual_outcome.get('result', ''),
        'key_insight': actual_outcome.get('key_insight', ''),
        'summary': comparison.get('summary', '')
    }


def run_real_case_batch(n=10):
    """실제 사례 n개 실행. 미실행 부족 시 get_unrun_real_cases에서 자동 생성."""
    cases = get_unrun_real_cases(n)
    results = []
    newly_generated = 0

    for case in cases:
        try:
            result = run_one_real_case(case)
            results.append({'ok': True, **result})
        except Exception as e:
            results.append({'ok': False, 'error': str(e)})

    # 실행 후 잔여 확인 — 10개 이하면 미리 10개 더 생성
    remaining = count_unrun_real_cases()
    if remaining <= 10:
        try:
            new_cases = generate_new_cases(10)
            newly_generated = len(new_cases)
        except Exception:
            newly_generated = 0

    return results, newly_generated


def reprocess_existing_real_cases(full=True):
    """기존에 돌린 실제 사례들을 새 프롬프트로 완전 재처리.
    full=True: 에이전트 판단 + 비교 분석 둘 다 재실행 (완전 재처리)
    full=False: 비교 분석만 재실행
    """
    conn = db.get_conn()
    rows = conn.execute(
        'SELECT * FROM real_case_simulations ORDER BY created_at ASC'
    ).fetchall()
    conn.close()

    total = len(rows)
    updated = 0
    new_patterns_total = 0

    for row in rows:
        try:
            scenario = json.loads(row['scenario_json'])
            actual_outcome = json.loads(row['actual_outcome_json'])

            # full=True: 에이전트 판단도 새 프롬프트로 재실행
            if full:
                agent_judgment = evaluate_with_brain(scenario)
            else:
                agent_judgment = json.loads(row['agent_judgment_json'])

            # 비교 분석 재실행 (항상)
            new_comparison = compare_judgment_to_outcome(scenario, agent_judgment, actual_outcome)

            match_score = new_comparison.get('match_score', 0)
            aligned = new_comparison.get('aligned', False)

            # 패턴 자동 추가 (성공 + 일치 + 고신뢰도)
            added_ids = []
            outcome_val = actual_outcome.get('outcome', '')
            if aligned and outcome_val == 'success':
                for p in new_comparison.get('new_patterns', []):
                    rule = p.get('rule', '').strip()
                    if p.get('confidence', 0) >= 80 and _is_valid_pattern(rule):
                        new_id = db.add_pattern(p['category'], rule)
                        added_ids.append(new_id)
                        new_patterns_total += 1

            # DB 업데이트 (에이전트 판단도 같이)
            conn = db.get_conn()
            if full:
                conn.execute(
                    '''UPDATE real_case_simulations
                       SET agent_judgment_json=?, comparison_json=?,
                           match_score=?, aligned=?, new_patterns_added=?,
                           patterns_fired=?, flagged=?
                       WHERE id=?''',
                    (json.dumps(agent_judgment, ensure_ascii=False),
                     json.dumps(new_comparison, ensure_ascii=False),
                     match_score,
                     1 if aligned else 0,
                     json.dumps(added_ids),
                     json.dumps(agent_judgment.get('patterns_fired', [])),
                     0 if aligned else 1,
                     row['id'])
                )
            else:
                conn.execute(
                    '''UPDATE real_case_simulations
                       SET comparison_json=?, match_score=?, aligned=?, new_patterns_added=?
                       WHERE id=?''',
                    (json.dumps(new_comparison, ensure_ascii=False),
                     match_score,
                     1 if aligned else 0,
                     json.dumps(added_ids),
                     row['id'])
                )
            conn.commit()
            conn.close()
            updated += 1
            print(f"  재처리 완료 ({updated}/{total}): {row['company']}")

        except Exception as e:
            print(f"  재처리 오류 (id={row['id']}): {e}")

    return {'total': total, 'updated': updated, 'new_patterns': new_patterns_total}


def generate_weekly_report(week_start):
    simulations = db.get_simulations_for_week(week_start)
    if not simulations:
        return None

    total = len(simulations)
    avg_conf = sum(s['confidence'] for s in simulations) / total
    flagged = [s for s in simulations if s['flagged']]

    freq = {}
    for s in simulations:
        for pid in s['patterns_fired']:
            freq[pid] = freq.get(pid, 0) + 1
    top_patterns = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]

    all_gaps = []
    for s in simulations:
        all_gaps.extend(s['gaps'])
    unique_gaps = list(dict.fromkeys(all_gaps))  # dedupe, preserve order

    patterns_data = json.loads(PATTERNS_PATH.read_text(encoding='utf-8'))
    pattern_map = {p['id']: p['rule'] for p in patterns_data['patterns']}

    report = {
        'week_start': week_start,
        'total_simulations': total,
        'avg_confidence': round(avg_conf, 1),
        'flagged_count': len(flagged),
        'reviewed_count': sum(1 for s in simulations if s['reviewed']),
        'top_patterns': [
            {'id': pid, 'rule': pattern_map.get(pid, f'패턴 #{pid}'), 'count': cnt}
            for pid, cnt in top_patterns
        ],
        'recurring_gaps': unique_gaps[:5],
        'flagged_cases': [
            {
                'id': s['id'],
                'industry': s['scenario'].get('industry', ''),
                'judgment': s['response'].get('judgment', ''),
                'confidence': s['confidence'],
                'gaps': s['gaps'],
                'reviewed': s['reviewed']
            }
            for s in flagged
        ]
    }

    db.save_weekly_report(week_start, report)
    return report
