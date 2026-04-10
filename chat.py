# -*- coding: utf-8 -*-
import json
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


def _build_patterns_str():
    try:
        patterns_data = db.get_patterns()
        patterns = patterns_data.get('patterns', [])
    except Exception:
        return ""

    cats = {}
    for p in patterns:
        cats.setdefault(p['category'], []).append(p['rule'])

    lines = []
    for cat, rules in cats.items():
        lines.append(f"[{cat}]")
        for r in rules[:8]:  # 카테고리당 최대 8개
            lines.append(f"  - {r[:120]}")
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


def build_system_prompt(section: str = 'marketing'):
    patterns_str = _build_patterns_str()
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

{PROBING_INSTRUCTION}

[응답 길이]
- 짧게. 대화체로. 필요한 말만.
"""


def get_brain_response(conversation_id: int, user_message: str, user_name: str,
                        section: str = 'marketing') -> str:
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    history = db.get_conversation_messages(conversation_id)
    system_prompt = build_system_prompt(section)

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

    prompt = f"""인하우스 마케터가 직원에게 실제 클라이언트 케이스를 던지는 상황이다.
목적: 직원이 '{context}'을 직접 기획해보는 훈련.

케이스 조건:
- 다양한 업종 (헬스장, 스킨케어, 학원, 식당, SaaS, 인테리어, 의류 등 — 매번 다르게)
- 마케팅/기획 관련 수치 포함 (월 매출, 예산, 고객 수, 캠페인 성과 등 — 전환율에 고착 금지)
- 실제 마케터가 맞닥뜨리는 고민 담기
- 보유 자산 포함 (기존 고객 DB, SNS, 후기, 파트너십 등)

케이스를 자연스러운 대화체로 던져라.
형식 예시: "자, 케이스 하나 줄게. [상황 설명]. 이 상황에서 어떻게 하겠어?"
조건: 한국어로, 250자 이내, 대화체로, 마지막은 반드시 질문으로 끝낼 것."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=350,
        temperature=0.9
    )
    return response.choices[0].message.content


def _generate_content_opening(section: str, client) -> str:
    """콘텐츠 전용 케이스 — 상황 유형을 다양하게 강제"""
    import random

    content_type = "유튜브 숏폼 영상" if section == 'content_youtube' else "네이버 블로그"

    # 업종 풀 — 매번 다르게
    industries = [
        "필라테스 스튜디오", "동네 카페", "온라인 영어 과외", "중고차 딜러",
        "펫샵", "네일샵", "한의원", "자동차 튜닝샵", "홈베이킹 클래스",
        "독립서점", "수제맥주 바", "요가 스튜디오", "키즈 카페", "가구 공방",
        "스킨케어 브랜드", "파티용품 쇼핑몰", "플로리스트", "닭갈비 식당",
        "수영 개인레슨", "심리상담 센터", "드라이브인 세차장", "소형 헬스장"
    ]

    # 콘텐츠 고민 유형 풀 — 다양한 상황
    challenges = [
        "조회수는 나오는데 팔로워가 안 늘어남",
        "영상 올릴 때마다 주제가 달라서 채널 색깔이 없음",
        "경쟁 채널이랑 내용이 비슷해 보여 차별점이 없음",
        "조회수도 팔로워도 없는 완전 신규 계정",
        "예전엔 잘 됐는데 최근 6개월 동안 조회수가 반 토막",
        "영상 보는 사람은 있는데 문의/구매로 이어지지 않음",
        "댓글은 많은데 저장이나 공유가 거의 없음",
        "타깃 고객이 아닌 엉뚱한 사람들이 보고 있음",
        "콘텐츠 아이디어가 바닥나서 뭘 만들어야 할지 모름",
        "첫 3초 이탈률이 너무 높음",
        "업로드 주기가 불규칙해서 구독자 이탈이 심함",
        "광고는 돌리는데 오가닉 채널이 전혀 성장 안 함"
    ]

    # 자산 유형 풀
    assets = [
        "기존 고객 후기 20여 개, 인스타 팔로워 800명",
        "네이버 블로그 방문자 하루 200명, 카카오채널 구독자 300명",
        "유튜브 구독자 500명 (업로드 6개월째 멈춤)",
        "오프라인 단골 고객 150명, 카카오톡 채널 400명",
        "인스타 팔로워 2,000명이지만 인게이지먼트율 0.5% 이하",
        "틱톡 팔로워 3,000명, 유튜브는 신규",
        "자체 제작 사진/영상 소스 풍부, SNS 미운영",
        "구글 리뷰 별점 4.8 / 리뷰 80개 보유"
    ]

    industry = random.choice(industries)
    challenge = random.choice(challenges)
    asset = random.choice(assets)

    prompt = f"""인하우스 마케터가 직원에게 {content_type} 기획 훈련 케이스를 던진다.

클라이언트 정보 (이걸 기반으로 케이스 작성):
- 업종: {industry}
- 핵심 고민: {challenge}
- 보유 자산: {asset}

위 정보를 활용해 실제 같은 케이스를 자연스러운 대화체로 구성하라.
수치를 구체적으로 넣고 (팔로워 수, 운영 기간, 콘텐츠 수 등 — 전환율만 고정 금지),
마지막은 "{content_type}으로 뭘 기획하겠어?" 형태의 질문으로 끝낼 것.
한국어로, 280자 이내."""

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=380,
        temperature=1.0  # 최대 다양성
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
