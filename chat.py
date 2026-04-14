# -*- coding: utf-8 -*-
import json
import random
from pathlib import Path
from openai import OpenAI
import db
from config_helper import get_config

BASE_DIR = Path(__file__).parent
PATTERNS_PATH = BASE_DIR / "brain" / "patterns.json"

BRAIN_FRAMEWORK = """
[사고 프레임워크 — 모든 판단의 기준]

핵심 3축:
- Outside-In: 판단 시작은 항상 외부. 경쟁사/시장/환경부터. 내부 문제로 단정 전에 외부 요인 먼저 소거.
- Asset Conversion: 새로 만들기 전에 이미 가진 것의 전환 가능성 먼저. 기존 고객, DB, 팔로워, 후기, 파트너십.
- System Thinking: 단발 이벤트가 아닌 반복되는 구조. 한 번 설계하면 계속 굴러가는 구조인지.

고유 사고 시그니처 5가지:
① 판 바꾸기: 약점이 있을 때 보완하지 않는다. 경쟁 축 자체를 바꾼다.
② 타겟 착시 간파: 인구통계가 같아도 구매 의도(intent)가 다르면 전환 안 된다.
③ 증명 우선: 말로 설명하지 않는다. 이벤트/수치/장면으로 증명.
④ 레버리지 연결: 확정된 것을 미확정 협상의 레버리지로. 빈손으로 협상 가지 않는다.
⑤ 수치 타겟화: 막연한 그룹이 아니라 비율/수치로 타겟을 구체화.
"""


_EMBED_TOP_K = 250      # 시맨틱 서치로 가져올 패턴 수
_FALLBACK_LIMIT = 30   # 임베딩 실패 시 카테고리당 최대 수


def _build_patterns_str(user_message: str = "") -> str:
    """
    user_message가 있으면 벡터 임베딩 시맨틱 서치로 관련 패턴 top-250 반환.
    임베딩 실패 시 기존 키워드 방식으로 폴백.
    """
    try:
        if user_message:
            import embeddings
            selected = embeddings.search_patterns(user_message, top_k=_EMBED_TOP_K)
            if selected:
                by_cat: dict = {}
                for p in selected:
                    by_cat.setdefault(p['category'], []).append(p['rule'])
                lines = []
                for cat, rules in by_cat.items():
                    lines.append(f"[{cat}]")
                    for r in rules:
                        lines.append(f"  - {r[:150]}")
                return "\n".join(lines)
    except Exception as e:
        print(f"[임베딩 서치 실패, 폴백] {e}")

    # 폴백: 키워드 기반 샘플링
    return _build_patterns_str_fallback(user_message)


def _build_patterns_str_fallback(user_message: str = "") -> str:
    """기존 키워드 매칭 + 랜덤 샘플 방식 (임베딩 실패 시 폴백)"""
    _SIGNATURE_CATS = {
        '판 바꾸기', '타겟 착시 간파', '증명 우선', '수치 타겟화',
        '레버리지 연결', '외부 우선 (Outside-In)', '위기 / 정체 대응',
        '감성적 포지셔닝', '체험 이벤트',
    }
    try:
        patterns_data = db.get_patterns()
        patterns = patterns_data.get('patterns', [])
    except Exception:
        return ""

    if not patterns:
        return ""

    keywords = [w for w in user_message.replace(',', ' ').split() if len(w) >= 2] if user_message else []

    cats: dict = {}
    for p in patterns:
        cats.setdefault(p['category'], []).append(p)

    selected: list = []
    for cat, cat_patterns in cats.items():
        if cat in _SIGNATURE_CATS or len(cat_patterns) <= 50:
            selected.extend(cat_patterns)
        else:
            if keywords:
                def relevance(p):
                    rule_lower = p['rule'].lower()
                    return sum(1 for kw in keywords if kw in rule_lower)
                scored = sorted(cat_patterns, key=relevance, reverse=True)
                top = scored[:_FALLBACK_LIMIT // 2]
                rest = random.sample(scored[_FALLBACK_LIMIT // 2:], min(_FALLBACK_LIMIT // 2, len(scored) - _FALLBACK_LIMIT // 2))
                selected.extend(top + rest)
            else:
                selected.extend(random.sample(cat_patterns, min(_FALLBACK_LIMIT, len(cat_patterns))))

    by_cat: dict = {}
    for p in selected:
        by_cat.setdefault(p['category'], []).append(p['rule'])

    lines = []
    for cat, rules in by_cat.items():
        lines.append(f"[{cat}]")
        for r in rules:
            lines.append(f"  - {r[:150]}")
    return "\n".join(lines)


SECTION_PROMPTS = {
    'marketing': """
[섹션: 마케팅]
마케팅 전략, 채널, 예산, 타겟에 대한 판단을 같이 발전시키는 대화다.
상대의 마케팅 상황을 듣고, 판단 프레임워크로 방향을 잡아준다.
""",
    'planning': """
[섹션: 기획]
사업 기획, 신규 서비스, 캠페인 기획 전반에 대한 논의다.
아이디어를 구조화하고, 빠진 부분을 짚어주고, 실행 가능한 형태로 만드는 것이 목표다.
""",
    'content_youtube': """
[섹션: 콘텐츠 — 유튜브 숏폼]
너는 클라이언트 케이스를 제시하고, 상대방의 영상 기획을 평가하는 역할이다.

영상 기획 평가 기준:
1. 공감/문제 포인트가 타겟에게 실제로 와닿는가?
2. 흥미를 유발하는가? — 재밌지 않으면 탈락
3. 첫 3초가 스크롤을 멈추게 하는가?
4. 말로 설명하지 않고 장면으로 보여주는가?
5. 저장/공유할 이유가 있는가?

평가 방식: 좋은 점 먼저 → 약한 점 구체적으로 → 더 나은 방향 제시
""",
    'content_blog': """
[섹션: 콘텐츠 — 네이버 블로그]
너는 클라이언트 케이스를 제시하고, 상대방의 블로그 기획을 평가하는 역할이다.

블로그 기획 평가 기준:
1. 검색 수요가 있는 키워드를 잡았는가?
2. 경쟁사가 안 가는 각도인가?
3. 제목이 타겟의 고통/욕망/역전을 건드리는가?
4. 첫 문단이 "내 얘기다" 느낌을 주는가?
5. H2 구조가 정보 나열이 아닌 판단형 흐름인가?
6. CTA가 감정이 가장 높은 순간에 있는가?

평가 방식: 좋은 점 먼저 → 약한 점 구체적으로 → 더 나은 방향 제시
"""
}

PROBING_INSTRUCTION = """
[상대방 사고 로직 파악 — 중요]
대화 중 상대가 방향을 정하거나 의견을 낼 때, 그 이유를 자연스럽게 파악하라.
- 매 응답마다 묻지 마라. 3~4턴에 한 번, 자연스러운 타이밍에만.
- 짧고 가볍게: "어떤 느낌에서요?", "뭐가 먼저 걸렸어요?", "그 방향으로 잡은 이유가요?", "어디서 막혔어요?"
- 한 번에 하나만. 심문 느낌 절대 안 된다.
- 상대가 바로 답하지 않으면 넘어가라.
"""

PERSPECTIVE_EXPANSION = """
[사고 확장 — 핵심]
상대가 기획이나 판단을 내놓으면, 단순 평가에 그치지 말고 사고를 넓혀줘라.

① 가정 뒤집기 (매 응답마다 하나)
  - 상대 기획에서 당연하게 깔고 있는 가정을 하나 골라라.
  - "근데 만약 [그 가정]이 틀렸다면? 그럼 방향이 어떻게 달라져?"
  - 예: "타깃이 20대라고 했는데, 실제 구매는 40대가 한다면?"
  - 예: "온라인이 답이라고 봤는데, 오프라인이 오히려 레버리지라면?"

② 각도 전환 (2~3턴에 한 번)
  - 같은 케이스를 전혀 다른 관점에서 한 줄로 던져라.
  - 고객 관점: "이걸 사는 사람 입장에서 보면 뭐가 트리거야?"
  - 경쟁사 관점: "경쟁사가 이걸 보면 어디서 기회를 볼까?"
  - 5년 후 관점: "이 전략이 구조로 굳어지면 어떤 자산이 생겨?"

③ 교차 산업 연결 (3~4턴에 한 번, 자연스러울 때만)
  - 완전 다른 업종이 비슷한 문제를 어떻게 풀었는지 한 줄로 던져라.
  - "이거 넷플릭스가 콘텐츠 다양성 문제 풀 때랑 비슷한 구조야."
  - "스타벅스가 '공간' 팔기 시작한 것처럼 포지셔닝을 바꾸면 어때?"
  - 강요하지 마라. 진짜 연결될 때만.

④ 의외의 관점 정리 (4~5턴마다 한 번)
  - "지금까지 나온 것 중에 제일 의외였던 건 [X]야. 이게 패턴이 될 수 있어."
  - 자연스러운 흐름에서 나올 때만.

규칙:
- 위 4가지를 전부 매번 하지 마라. 흐름 보고 하나씩.
- 평가 → 확장 → 질문 순서로. 확장이 설교가 되면 안 된다.
- 짧고 자연스럽게. 강의 느낌 금지.
"""


def build_system_prompt(section: str = 'marketing', user_message: str = ""):
    patterns_str = _build_patterns_str(user_message)
    section_prompt = SECTION_PROMPTS.get(section, SECTION_PROMPTS['marketing'])

    return f"""너는 인하우스 마케터이자 전략가다.
{section_prompt}
{BRAIN_FRAMEWORK}

[축적된 판단 패턴]
{patterns_str}

[대화 방식]
- 판단형으로 말한다. 분석 리포트 쓰지 않는다.
- "지금 이걸 해라, 이유는 이거다" 형태로.
- 상대 아이디어가 좋으면 왜 좋은지 짧게 말하고 더 발전시킨다.
- 상대 아이디어가 약하면 어디가 약한지 구체적으로 말하고 더 나은 방향을 제시한다.
- 대화체로. 짧고 명확하게.

{PERSPECTIVE_EXPANSION}

{PROBING_INSTRUCTION}

[응답 길이]
- 짧게. 대화체로. 필요한 말만.
- 사고 확장은 한 번에 하나. 한 응답에 4가지 다 넣지 마라.
"""


def get_brain_response(conversation_id: int, user_message: str, user_name: str,
                        section: str = 'marketing') -> str:
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    history = db.get_conversation_messages(conversation_id)
    system_prompt = build_system_prompt(section, user_message)

    messages = [{"role": "system", "content": system_prompt}]
    for m in history:
        messages.append({"role": m['role'], "content": m['content']})
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=800,
        temperature=0.5
    )

    return response.choices[0].message.content


def generate_content_case(content_type: str) -> dict:
    """콘텐츠 탭용 클라이언트 케이스 자동 생성"""
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    type_label = "유튜브 숏폼 영상" if content_type == 'youtube' else "네이버 블로그 포스팅"

    prompt = f"""다양한 업종의 실제 같은 클라이언트 케이스를 하나 만들어라.
목적: 직원이 이 케이스를 보고 {type_label} 기획을 직접 해보는 훈련용.

케이스 조건:
- 다양한 업종 (매번 다르게)
- 구체적인 상황과 수치 포함
- 실제 마케팅 고민이 담길 것
- 보유 자산 포함 (기존 고객, SNS, 후기 등)

JSON으로 반환:
{{
  "industry": "업종",
  "situation": "현재 상황 (2~3문장, 구체적 수치 포함)",
  "goal": "목표",
  "assets": "보유 자산",
  "constraint": "제약 사항 (예산, 인력 등)"
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.9
    )

    try:
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {"error": "케이스 생성 실패"}


PHASE_THRESHOLD = 50  # 이 수 이상이면 2단계


def get_current_phase() -> int:
    data = db.get_patterns()
    return 2 if len(data.get('patterns', [])) >= PHASE_THRESHOLD else 1


def generate_opening_message(section: str) -> str:
    """세션 시작 시 뇌가 먼저 던지는 케이스 메시지"""
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    context_map = {
        'marketing':       '마케팅 전략/채널/타겟 고민',
        'planning':        '사업 기획/캠페인/신규 서비스',
        'content_youtube': '유튜브 숏폼 영상 기획',
        'content_blog':    '네이버 블로그 기획',
    }
    context = context_map.get(section, '마케팅')

    # 콘텐츠 섹션은 전용 프롬프트로 분기
    if section in ('content_youtube', 'content_blog'):
        return _generate_content_opening(section, client)

    prompt = f"""인하우스 마케터가 직원에게 실제 클라이언트 케이스를 브리핑하는 상황이다.
목적: 직원이 '{context}'을 직접 기획해보는 훈련.

케이스에 반드시 포함할 내용 (추가 질문 없이 바로 기획할 수 있을 만큼 상세하게):
1. 업종 + 사업 형태 (오프라인/온라인/혼합, 규모)
2. 현재 상황 수치 (매출, 고객 수, 성장률 등 — 전환율 고착 금지, 다양한 지표 사용)
3. 타깃 고객 (누구인지, 왜 오는지)
4. 현재 마케팅/기획 현황 (지금 뭘 하고 있는지, 어디서 막혔는지)
5. 보유 자산 (DB, SNS, 후기, 파트너십, 예산 등)
6. 핵심 고민 (왜 지금 이 고민을 하는지 배경까지)

대화체로 자연스럽게 던져라. 딱딱한 보고서 형식 금지.
업종은 의외의 업종도 좋음 (헬스장·카페·학원 반복 금지).
마지막은 구체적인 질문으로 끝낼 것 ("이 상황에서 어떻게 하겠어?" 형태).
한국어로, 600자 내외."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=700,
        temperature=0.9
    )
    return response.choices[0].message.content


def _generate_content_opening(section: str, client) -> str:
    """콘텐츠 전용 케이스 — 성장 단계 기반으로 다양성 확보"""

    content_type = "유튜브 숏폼 영상" if section == 'content_youtube' else "네이버 블로그"

    # 핵심 차원: 성장 단계 (스펙트럼 전체 커버)
    growth_stages = [
        {
            "stage": "완전 신규",
            "desc": "SNS 계정 자체가 없거나 막 만든 수준. 팔로워 0, 콘텐츠 경험 없음.",
            "challenge_pool": [
                "어디서 어떻게 시작해야 할지 모름",
                "첫 콘텐츠 주제를 뭘로 잡아야 할지 막막",
                "경쟁이 너무 많아 보여 시작 자체를 못 하고 있음",
            ]
        },
        {
            "stage": "방향 탐색기",
            "desc": "콘텐츠 몇 개 올려봤지만 반응이 없고 방향을 못 잡음. 팔로워 50명 이하.",
            "challenge_pool": [
                "올려도 조회수가 30~50회에서 안 올라감",
                "뭘 올려야 사람들이 볼지 감이 없음",
                "주제가 계속 바뀌어서 채널 색깔이 없음",
            ]
        },
        {
            "stage": "초기 성장기",
            "desc": "팔로워 100~500명. 가끔 반응 오지만 일관성 없이 들쭉날쭉.",
            "challenge_pool": [
                "몇 개 영상은 터지는데 나머지는 죽어있음",
                "알고리즘이 어떻게 작동하는지 전혀 모름",
                "첫 3초 이탈률이 높아서 영상이 퍼지질 않음",
            ]
        },
        {
            "stage": "정체기",
            "desc": "팔로워 1,000~5,000명에서 수개월째 성장이 멈춤. 열심히 하는데 안 늘어남.",
            "challenge_pool": [
                "열심히 올리는데 팔로워가 수개월째 제자리",
                "기존 팬은 있는데 신규 유입이 없음",
                "비슷한 업종 채널은 성장하는데 나만 멈춘 느낌",
            ]
        },
        {
            "stage": "하락기",
            "desc": "한때 잘 됐지만 최근 몇 달 조회수·팔로워가 눈에 띄게 감소.",
            "challenge_pool": [
                "예전에 잘 됐던 포맷이 갑자기 반응 없어짐",
                "알고리즘 변경 이후 노출이 반 토막",
                "콘텐츠 번아웃으로 업로드가 불규칙해지며 이탈 증가",
            ]
        },
        {
            "stage": "성숙·전환 문제",
            "desc": "팔로워 1만명 이상. 보는 사람은 많은데 실제 매출·문의로 안 이어짐.",
            "challenge_pool": [
                "팔로워는 많은데 실제 고객이 아닌 구경꾼들임",
                "콘텐츠 보고 오는 사람이 많아도 구매 전환이 안 됨",
                "인지도는 생겼지만 팬덤이나 충성도가 없음",
            ]
        },
        {
            "stage": "한계 돌파",
            "desc": "어느 정도 자리잡았지만 현재 한계에 부딪혀 다음 레벨로 가고 싶음.",
            "challenge_pool": [
                "광고 없이 오가닉으로 더 올리고 싶은데 방법을 모름",
                "채널 규모 대비 수익이 너무 낮음",
                "콘텐츠 포맷을 바꿔야 할 것 같은데 어떻게 바꿔야 할지 모름",
            ]
        },
    ]

    stage = random.choice(growth_stages)
    challenge = random.choice(stage['challenge_pool'])

    prompt = f"""인하우스 마케터가 직원에게 {content_type} 기획 훈련 케이스를 브리핑한다.

클라이언트 상황:
- 성장 단계: {stage['stage']} — {stage['desc']}
- 핵심 고민: {challenge}
- 업종: 자유롭게 설정 (의외의 업종 환영, 헬스장·카페·학원 반복 금지)

케이스에 반드시 포함할 내용 (추가 질문 없이 바로 기획 들어갈 수 있을 만큼 상세하게):
1. 업종 + 사업 구체적 설명 (규모, 운영 형태)
2. 채널 현황 수치 (팔로워 수, 게시물 수, 평균 조회수, 업로드 주기 등 — 성장 단계에 맞게)
3. 현재 올리고 있는 콘텐츠 스타일/주제
4. 타깃 고객 (누가 보는지, 실제 고객이랑 맞는지)
5. 보유 자산 (기존 콘텐츠 소스, 고객 후기, 예산, 협력 가능한 것들)
6. 핵심 고민 배경 (왜 지금 이 고민이 생겼는지)

대화체로 자연스럽게 던져라. 보고서 형식 금지.
마지막은 "{content_type}으로 뭘 기획하겠어?" 형태 질문으로 끝낼 것.
한국어, 650자 내외."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=750,
        temperature=1.0
    )
    return response.choices[0].message.content


def generate_phase2_opening(section: str) -> str:
    """2단계: 뇌가 케이스 + 자기 판단을 먼저 공유"""
    client = OpenAI(api_key=get_config().get('openai_api_key'))
    patterns_str = _build_patterns_str()

    context_map = {
        'marketing':       '마케팅 전략/채널/타겟',
        'planning':        '사업 기획/캠페인',
        'content_youtube': '유튜브 숏폼 영상',
        'content_blog':    '네이버 블로그',
    }
    context = context_map.get(section, '마케팅')

    prompt = f"""너는 축적된 판단 패턴을 가진 인하우스 마케터다.

[판단 패턴]
{patterns_str}

역할:
1. 다양한 업종의 실제 같은 클라이언트 케이스를 제시한다 (구체적 수치 포함)
2. 위 패턴을 기반으로 너의 판단을 먼저 공유한다 (핵심만, 2~3줄)
3. 상대에게 다른 각도나 추가 관점이 있는지 열린 질문을 던진다

섹션: {context}
조건: 한국어로, 대화체로, 400자 이내, 마지막은 반드시 열린 질문으로 끝낼 것

형식:
"자, 케이스 하나. [케이스 내용]

나 기준으로는: [핵심 판단]

어떻게 봐? 다른 각도 있어?" """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.8
    )
    return response.choices[0].message.content


def extract_patterns_from_conversation(conversation_id: int) -> list:
    """대화에서 패턴 후보 추출"""
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    messages_raw = db.get_conversation_messages(conversation_id)
    if not messages_raw:
        return []

    conversation_text = "\n".join([
        f"[{'뇌' if m['role'] == 'assistant' else m.get('user_name', '사용자')}] {m['content']}"
        for m in messages_raw
    ])

    prompt = f"""다음 대화에서 마케팅/기획/콘텐츠 판단 패턴으로 추출할 수 있는 인사이트를 찾아라.

대화:
{conversation_text}

패턴 추출 기준:
- 반복해서 써먹을 수 있는 판단 원칙
- "이런 상황에서는 이렇게 한다" 형태로 일반화 가능한 것
- 너무 케이스 특수적인 것은 제외

JSON으로 반환: {{"patterns": [{{"category": "카테고리명", "rule": "패턴 내용"}}, ...]}}
없으면: {{"patterns": []}}
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.3
    )

    try:
        result = json.loads(response.choices[0].message.content)
        return result.get('patterns', [])
    except Exception:
        return []
