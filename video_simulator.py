# -*- coding: utf-8 -*-
"""
영상 기획 자동 시뮬레이터
랜덤 브랜드 시나리오 생성 → 뇌 에이전트 → 영상 기획 뇌 → 완성안 → DB 저장
"""
import json
import random

from openai import OpenAI
import anthropic
import db
from agent import analyze, video_plan_brain
from config_helper import get_config

# 유튜브 쇼츠 광고에 적합한 업종 풀 (오프라인/소비자 대상 위주)
SHORTS_INDUSTRIES = [
    "포장이사/이삿짐센터", "피부과/에스테틱", "치과/임플란트", "한의원",
    "인테리어/리모델링", "헬스장/PT샵", "요가/필라테스 스튜디오",
    "네일샵/속눈썹샵", "카페/디저트 매장", "식당/배달 전문점",
    "자동차 세차/튜닝", "펫샵/반려동물 용품", "결혼준비/웨딩플래너",
    "학원/과외", "공인중개사/부동산", "세탁소/수선집",
    "꽃집/플라워샵", "약국/건강기능식품", "육아용품/유아복",
    "주방용품/생활용품 쇼핑몰"
]

BRAND_ARCHETYPES = [
    {"goal": "견적/상담 문의 유도", "ages": "30대~50대", "tone": "신뢰, 전문성"},
    {"goal": "매장 방문 유도", "ages": "20대~40대", "tone": "친근함, 재미"},
    {"goal": "앱 다운로드 / 회원가입 유도", "ages": "20대~30대", "tone": "빠름, 간결"},
    {"goal": "구매 전환 (이커머스)", "ages": "25대~45대", "tone": "신뢰, 혜택 강조"},
    {"goal": "브랜드 인지도 상승", "ages": "20대~40대", "tone": "유머, 임팩트"},
]

STRENGTH_POOL = [
    ["당일 예약 가능", "후기 500개 이상", "3년 연속 1위"],
    ["전문가 직접 담당", "100% 환불 보장", "출장 서비스"],
    ["무료 상담 제공", "전국 서비스 가능", "24시간 대응"],
    ["특허 기술 보유", "5년 이상 경력", "기업 고객 300곳"],
    ["친환경 재료 사용", "당일 배송 가능", "커스텀 제작"],
]

PROHIBITION_SYSTEM = """
너는 유튜브 쇼츠 광고 경쟁 분석가다.

[임무]
주어진 업종의 유튜브 쇼츠 광고에서 가장 흔하게 반복되는 광고 서사 구조 5가지를 뽑아라.

[기준]
- 광고 서사 기반. 드라마 스토리 구조 아님.
- "지친 사람이 → 제품/서비스로 → 힐링/해결" 같은 광고 흐름.
- 이 업종 광고 대부분이 공통으로 쓰는 패턴.
- 구체적인 광고 흐름으로. "감성 강조" 같은 추상어 금지.

[출력 형식 — JSON만]
{"banned_patterns": ["광고서사1", "광고서사2", "광고서사3", "광고서사4", "광고서사5"]}
"""

ROUND3_SYSTEM = """
너는 유튜브 쇼츠 촬영 감독이다.
2차 재설계안을 받아서 실제 촬영 지시서처럼 장면을 완성해라.

완성 기준:
- 장면 하나하나가 카메라 앞에서 바로 찍을 수 있게 선명해야 함
- 누가 어디서 무엇을 하는지 구체적으로
- 억지 설명 없음
- 마지막은 브랜드명 + 핵심 한 줄로만

[출력 형식]
장면1 (0-3초):
장면2 (3-10초):
장면3 (10-20초):
장면4 (20-30초):
마지막자막:
"""

ROUND2_SYSTEM = """
너는 유튜브 쇼츠 크리에이티브 디렉터다.
1차 기획의 실행 품질을 검토하고, 문제가 있는 부분만 개선해라.

[소거 목록]
{banned_patterns}

[검토 기준]
1. 소거 목록 위반 여부: 있으면 교체.
2. 직관성: 첫 3초 장면을 보고 상황이 즉각 이해되는가?
3. 재미/흥미: 첫 3초에 웃음, 충격, 강한 감정이 발생하는가?
4. 촬영 가능성: 판타지/합성 없이 실제 촬영 가능한가?
5. 마지막이 문구가 아닌 장면/감정인가?

[재설계 규칙]
- 방향이 맞고 위 5가지 문제가 없으면 비틀기 유형을 바꾸지 마라.
- 문제가 있는 부분만 정확하게 교체해라.

[출력 형식]
검토결과: (5가지 기준별 OK/NG + NG면 이유)
개선내용: (무엇을 왜 바꿨는지)
최종영상기획:
"""


def _get_clients():
    cfg = get_config()
    oai = OpenAI(api_key=cfg['openai_api_key'])
    cld = anthropic.Anthropic(api_key=cfg['anthropic_api_key'])
    return oai, cld


def _generate_brand() -> dict:
    """랜덤 브랜드 시나리오 생성"""
    industry = random.choice(SHORTS_INDUSTRIES)
    archetype = random.choice(BRAND_ARCHETYPES)
    strengths = random.choice(STRENGTH_POOL)

    brand_suffixes = ["플러스", "프로", "킹", "원", "365", "랩", "스튜디오"]
    brand_name = f"{industry.split('/')[0]}{random.choice(brand_suffixes)}"

    return {
        "brand_name": brand_name,
        "product_name": industry,
        "industry": industry,
        "goal": archetype["goal"],
        "ages": archetype["ages"],
        "product_strengths": " / ".join(strengths[:2]),
        "extra_strength": strengths[2],
        "tones": archetype["tone"],
        "action_style": archetype["goal"],
        "service_types": "오프라인 / 대면",
        "forbidden_phrases": "저렴한 / 착한 가격",
    }


def _situation_text(brand: dict) -> str:
    return f"""[고객사 정보]
브랜드명: {brand['brand_name']}
상품/서비스: {brand['product_name']}
업종: {brand['industry']}
서비스 형태: {brand.get('service_types', '')}

[마케팅 목표 & 타겟]
최우선 목표: {brand['goal']}
주요 타겟 연령대: {brand['ages']}

[강점 & 홍보 포인트]
강점: {brand['product_strengths']} / {brand.get('extra_strength', '')}

[콘텐츠 방향]
톤: {brand.get('tones', '')}
행동 유도: {brand.get('action_style', '')}
금지 표현: {brand.get('forbidden_phrases', '')}
"""


def run_video_simulation() -> dict:
    """
    전체 파이프라인 실행 후 결과를 DB에 저장.
    Returns: {'id': int, 'brand': dict, 'final_plan': str} or {'error': str}
    """
    try:
        oai, cld = _get_clients()
    except Exception as e:
        return {'error': f'API 클라이언트 오류: {e}'}

    # ── STEP 0: 브랜드 생성 ──────────────────────────────
    brand = _generate_brand()
    brand_info = _situation_text(brand)
    print(f"[영상 시뮬] 브랜드: {brand['brand_name']} ({brand['industry']})")

    # ── STEP 1: 경쟁 소거 ──────────────────────────────
    try:
        prohibit_resp = oai.chat.completions.create(
            model='gpt-4o',
            messages=[
                {'role': 'system', 'content': PROHIBITION_SYSTEM},
                {'role': 'user', 'content': f"업종: {brand['industry']}\n상품/서비스: {brand['product_name']}"}
            ],
            max_tokens=300,
            temperature=0.2,
            response_format={'type': 'json_object'}
        )
        prohibit = json.loads(prohibit_resp.choices[0].message.content)
    except Exception:
        prohibit = {'banned_patterns': []}

    banned = prohibit.get('banned_patterns', [])
    banned_str = "\n".join(f"- {p}" for p in banned)

    # ── STEP 2: 뇌 에이전트 판단 ─────────────────────────
    brand_info_with_ban = brand_info + f"\n[소거 목록]\n{banned_str}\n"
    brain = analyze(brand_info_with_ban)
    print(f"[영상 시뮬] 판단: {brain.get('judgment', '')[:60]}...")

    # ── STEP 3: 영상 기획 뇌 (케이스 기반) ──────────────
    draft = video_plan_brain(brain, brand_info, banned_str)
    print(f"[영상 시뮬] 초안 생성 완료")

    # ── STEP 4: 비판 + 재설계 ────────────────────────────
    r2_system = ROUND2_SYSTEM.format(banned_patterns=banned_str)
    try:
        r2_resp = cld.messages.create(
            model='claude-opus-4-6',
            max_tokens=4000,
            thinking={'type': 'adaptive'},
            messages=[{
                'role': 'user',
                'content': r2_system + f"\n\n[브랜드 정보]\n{brand_info}\n\n[1차 기획안]\n{draft}"
            }]
        )
        revised = next((b.text for b in r2_resp.content if b.type == 'text'), draft)
    except Exception:
        revised = draft

    # ── STEP 5: 장면 완성 ────────────────────────────────
    try:
        r3 = oai.chat.completions.create(
            model='gpt-4o',
            messages=[
                {'role': 'system', 'content': ROUND3_SYSTEM},
                {'role': 'user', 'content': f"[브랜드 정보]\n{brand_info}\n\n[2차 재설계안]\n{revised}"}
            ],
            max_tokens=700,
            temperature=0.7
        )
        final_plan = r3.choices[0].message.content
    except Exception:
        final_plan = revised

    # ── 저장 ────────────────────────────────────────────
    sim_id = db.save_video_simulation(
        brand=brand,
        brain_judgment=brain,
        draft=draft,
        final_plan=final_plan
    )
    print(f"[영상 시뮬] 저장 완료 (#{sim_id})")
    return {'id': sim_id, 'brand': brand, 'final_plan': final_plan}
