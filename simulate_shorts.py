# -*- coding: utf-8 -*-
"""
쇼츠 비판 루프 시뮬레이션
뇌에이전트 판단 → Round1 초안 → Round2 비판+재설계 → Round3 장면 완성
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

import anthropic
from openai import OpenAI
from agent import analyze, video_plan_brain, extract_video_case_from_feedback
from config_helper import get_config

import db
cfg = get_config()
client = OpenAI(api_key=cfg.get('openai_api_key'))
claude = anthropic.Anthropic(api_key=cfg.get('anthropic_api_key'))
db.init_db()


def claude_generate(system_prompt: str, user_content: str, max_tokens: int = 16000) -> str:
    """Claude claude-opus-4-6 + extended thinking으로 생성"""
    resp = claude.messages.create(
        model='claude-opus-4-6',
        max_tokens=max_tokens,
        thinking={
            'type': 'adaptive'
        },
        messages=[
            {'role': 'user', 'content': system_prompt + "\n\n" + user_content}
        ]
    )
    for block in resp.content:
        if block.type == 'text':
            return block.text
    # 텍스트 블록이 없으면 블록 타입 로깅
    print(f"[경고] 텍스트 블록 없음. 블록 타입: {[b.type for b in resp.content]}")
    return ''

# ── 테스트 브랜드 ──────────────────────────────────────
TEST_BRAND = {
    "brand_name": "무브킹 이사센터",
    "product_name": "포장이사 / 원룸이사",
    "industry": "이사/이삿짐센터",
    "goal": "견적 문의 유도",
    "ages": "20대~40대",
    "product_strengths": "당일 예약 가능 / 파손 제로 보증 / 3인 전문팀 / 30분 내 견적 확정",
    "extra_strength": "이사 후 청소 서비스 포함 / 후기 500개 이상",
    "tones": "신뢰, 빠름",
    "action_style": "견적 문의 유도",
    "service_types": "오프라인 / 대면",
    "forbidden_phrases": "저렴한 / 착한 가격"
}

# ── 비틀기 예시 케이스 ─────────────────────────────────
# 각 예시에서 배울 것: "뻔한 방향" → "어떻게 뒤집었는가"의 사고 과정
# 배우지 말 것: 특정 업종 장면·레퍼런스·비유를 그대로 복사하지 마라
# 이 예시들은 어떤 업종이든 적용할 수 있는 비틀기 사고의 패턴을 보여준다
FEW_SHOT_PRINCIPLES = """
[비틀기 케이스 — 사고 방식만 배워라, 장면·레퍼런스 복사 금지]

부동산:
뻔한방향: 좋은 집 소개 + 문의
비틀기: 직원이 전화 폭주에 으아아아 소리 지르며, 집 보러 사람들이 우르르 뒤따라옴 → "대입보다 경쟁률 높은 부동산"
사고과정: 브랜드가 숨기고 싶은 것(경쟁)을 오히려 증거로 활용

학원:
뻔한방향: 합격 후기 + 성적 수치
비틀기: 주인공이 맨날 놀고 수업 때 잠만 자는데 → 서울대 합격 → "공부는 재밌어야 한다"
사고과정: 타겟이 가장 두려워하는 장면(놀고 자는 모습)으로 시작해서 원인을 역전

세무사:
뻔한방향: 절세 팁 + 상담
비틀기: 수돗꼭지에서 돈이 콸콸 새는데 수리기사가 자꾸 실패 → 다른 수리기사가 밀치고 탁 고침
사고과정: 추상적 손해(세금 낭비)를 물리적 장면(돈이 새는 수돗꼭지)으로 번역

금융/대출:
뻔한방향: 금리 비교 + 신청 유도
비틀기: 대출 압박 상징 인물 앞에서 절규 → 우리 상품이 드롭킥으로 날려버림
사고과정: 타겟의 적(압박)을 물리적으로 제거하는 장면

헬스장(소형):
뻔한방향: 몸매 변화 전후
비틀기: 대형 헬스장 앞에서 줄 서며 "여기 맛집인가봐" → 시점 전환, 소형 헬스장 1:1 PT 장면
사고과정: 경쟁사의 단점을 첫 장면으로 써서 우리가 다름을 역전으로 보여줌

보험:
뻔한방향: 위험 상황 + 가입 유도
비틀기: 차 사고 → 화면 분할, 한쪽 컬러(보험 있어서 해결) / 한쪽 흑백(가족 힘들어함)
사고과정: 동일 사건, 두 결말을 동시에 보여줌

카이로프랙틱:
뻔한방향: 통증 호소 + 치료 후 개선
비틀기: 몸 좋은 젊은이가 헉헉대며 뛰는데 → 옆에서 노인이 꼿꼿하게 훨씬 빠르게 앞서감
사고과정: 타겟이 절대 예상 못 할 장면(노인이 앞서감)으로 첫 3초 충격
"""

TWIST_TYPES = """
[비틀기 유형 17가지 — 뇌 에이전트 판단과 브랜드 팩트를 기반으로 하나를 선택하고 이유를 밝혀라]

결과 비틀기    : 예상 결과가 아닌 의외의 결과로 끝남
효과 비틀기    : 제품/서비스 효과가 과장되거나 의외의 방식으로 나타남
대비 비틀기    : 극단적 두 상황을 나란히 붙여 차이를 극대화
욕망 비틀기    : 타겟이 원하는 결과 장면을 먼저 보여주고 역행
증명 비틀기    : 설명 대신 수치/장면/반응으로 직접 증명
과정 비틀기    : 예상과 다른 방식으로 해결되는 과정
꿈→현실 비틀기 : 꿈 같은 장면이 현실임을 드러냄
비교역전 비틀기 : 열등해 보이던 것이 우월함이 드러남
예상역전 비틀기 : 시청자 예상과 정반대로 끝남
문화오마주 비틀기: 익숙한 영화/드라마/밈 장면을 업종에 이식 (단, 특정 작품명을 고정하지 말고 상황에 맞는 것을 찾아라)
은유→현실 비틀기: 추상적 은유(돈이 샌다 등)를 실제 장면으로
평행현실 대비  : 선택에 따른 두 현실을 동시에 보여줌
드라마틱 리빌  : 정체를 숨기다가 마지막에 한방에 드러냄
규모역전       : 작은 것이 큰 것을 압도하는 장면
개입역전       : 예상치 못한 존재/행동이 상황을 바꿈
권위 리빌      : 의외의 권위자가 등장해 신뢰를 단번에 확보
감정 구출 서사  : 힘든 상황에서 구출되는 감정 서사
"""

CASTING_GUIDE = """
[캐스팅 전략 — 반드시 명시]
- 타겟 연령대/상황과 일치하는 사람을 캐스팅해라
- 욕망형: 타겟보다 살짝 더 나은 상태의 사람 (타겟이 되고 싶은 모습)
- 공감형: 타겟과 완전히 동일한 상황의 사람 (내 얘기다 느낌)
- 역전형: 타겟이 예상하지 못한 사람 (반전 극대화)
- 출력에 캐스팅: [누가 / 어떤 상태] 명시 필수
"""

# ── 경쟁 소거 — banned_patterns만 담당 ─────────────────
PROHIBITION_SYSTEM = """
너는 유튜브 쇼츠 광고 경쟁 분석가다.

[임무]
주어진 업종의 유튜브 쇼츠 광고에서 가장 흔하게 반복되는 광고 서사 구조 5가지를 뽑아라.

[기준]
- 광고 서사 기반. 드라마 스토리 구조 아님.
- "지친 사람이 → 제품/서비스로 → 힐링/해결" 같은 광고 흐름.
- 이 업종 광고 대부분이 공통으로 쓰는 패턴.
- 구체적인 광고 흐름으로. "감성 강조" 같은 추상어 금지.
- 예시 형식: "지친 직장인이 자연 속 글램핑으로 힐링하는 서사"

[출력 형식 — JSON만]
{"banned_patterns": ["광고서사1", "광고서사2", "광고서사3", "광고서사4", "광고서사5"]}
"""

ROUND1_SYSTEM = """
너는 유튜브 쇼츠 영상 기획자다.

[뇌 에이전트 전략 판단]
{brain_judgment}

[번역된 장면 — 이것이 이번 영상의 출발점이다]
장면: {scene_line}
웃음 메커니즘: {mechanism}
이유: {scene_reason}

creative_approach: {creative_approach}
{approach_guide}

[소거 목록 — 이 패턴이 조금이라도 보이면 실패]
{banned_patterns}

[임무]
- 번역된 장면을 그대로 받아서 30초 영상 전체를 기획해라
- 첫 3초 장면은 이미 결정됐다. 더 웃기거나 충격적으로 만들 수 있으면 그렇게 해라
- 소거 목록 방향으로 가지 마라

[첫 3초 필수 조건 — 번역 장면을 발전시켜라]
- 시청자가 웃거나(ㅋㅋ) 놀라거나(어?) 공감 폭발해야 한다
- "쿨하게 보여주는" 장면은 실패다. 감정이 터져야 한다
- 등장인물의 과장된 리액션, 황당한 상황, 예상 밖 결과 중 하나가 첫 3초에 있어야 한다

[제약]
- 현실에서 실제 촬영 가능한 장면만. 판타지/합성/VFX 없음
- 마지막: 문구/자막이 아닌 장면/감정으로 끝내라

[출력 형식 — 간결하게]
뻔한방향: (소거한 방향 한 줄)
영상기획: (첫 장면 → 전개 → 마지막, 3줄 이내)
마지막자막: (브랜드명 + 핵심 한 줄)
"""

ROUND2_SYSTEM = """
너는 유튜브 쇼츠 크리에이티브 디렉터다.
1차 기획의 실행 품질을 검토하고, 문제가 있는 부분만 개선해라.

[creative_approach: {creative_approach}]
{approach_guide}

[소거 목록]
{banned_patterns}

[검토 기준 — 이 순서로 판단해라]
1. 소거 목록 위반 여부: 있으면 교체.
2. 직관성: 첫 3초 장면을 보고 상황이 즉각 이해되는가?
   - 3초 이상 생각해야 이해되면 NG.
   - "왜 저러지?" 다음에 "아, 저래서구나"가 5초 안에 오지 않으면 NG.
3. 재미/흥미: 첫 3초에 웃음, 충격, 강한 감정이 발생하는가?
   - "뭐지?" 만 있고 재미가 없으면 NG.
   - 스크롤 멈추는 이유가 "궁금해서"가 아니라 "재밌어서/놀라워서"여야 함.
4. 촬영 가능성: 판타지/합성 없이 실제 촬영 가능한가?
5. 마지막이 문구가 아닌 장면/감정인가?

[재설계 규칙]
- 방향이 맞고 위 5가지 문제가 없으면 비틀기 유형을 바꾸지 마라.
- 문제가 있는 부분만 정확하게 교체해라. 멀쩡한 걸 갈아엎지 마라.
- 직관성·재미가 NG면: 동일한 비틀기 유형을 유지하되, 첫 장면을 더 즉각적으로 웃기거나 충격적인 장면으로 교체해라.
- 마지막은 반드시 감정 장면으로.

[출력 형식]
검토결과: (5가지 기준별 OK/NG + NG면 이유)
개선내용: (무엇을 왜 바꿨는지 — 바꾼 것만)
최종영상기획:
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

APPROACH_GUIDES = {
    'strong_twist': '업종/장르/시대를 완전히 이탈해서 주목을 빼앗아라. 영상 속 맥락이 이 업종과 전혀 관계없어 보여야 한다. 마지막에야 연결된다.',
    'light_twist':  '업종 맥락 유지. 장면만 극적으로 비틀어라. 시청자가 "어? 이게 맞나?" 할 정도의 반전이면 충분하다.',
    'product_focus': '제품/서비스 자체가 가장 강한 증거다. 설명 없이 결과 장면만 보여줘라. 타겟이 이미 문제를 인식하고 있다.'
}


def situation_text(brand):
    return f"""
[고객사 정보]
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


def run() -> str:
    """Returns brand_info for post-run feedback extraction."""
    sep = "=" * 60
    output = []

    brand_info = situation_text(TEST_BRAND)

    # ── STEP 0: 경쟁 소거 먼저 (뇌 에이전트가 금지 패턴을 알아야 함) ──
    print(f"\n{sep}")
    print("STEP 0: 경쟁 소거 (업종 클리셰 추출)")
    print(sep)

    industry_info = f"업종: {TEST_BRAND['industry']}\n상품/서비스: {TEST_BRAND['product_name']}"
    prohibit_resp = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': PROHIBITION_SYSTEM},
            {'role': 'user', 'content': industry_info}
        ],
        max_tokens=300,
        temperature=0.2,
        response_format={'type': 'json_object'}
    )
    try:
        prohibit = json.loads(prohibit_resp.choices[0].message.content)
    except Exception:
        prohibit = {'banned_patterns': []}

    banned = prohibit.get('banned_patterns', [])
    banned_str = "\n".join(f"- {p}" for p in banned)

    print(f"소거 패턴:\n{banned_str}")
    output.append(sep)
    output.append("STEP 0: 경쟁 소거")
    output.append(sep)
    output.append(f"소거 패턴:\n{banned_str}")

    # ── STEP 1: 뇌 에이전트 판단 — 소거 목록 주입 후 실행 ──
    print(f"\n{sep}")
    print("STEP 1: 뇌 에이전트 판단 (패턴 기반 + 소거 목록 인지)")
    print(sep)

    # 소거 목록을 brand_info에 추가해서 뇌 에이전트가 인지하게 함
    brand_info_with_ban = brand_info + f"""
[이 업종의 소거 목록 — action 방향에 이 패턴이 들어가면 안 됨]
{banned_str}
"""

    brain = analyze(brand_info_with_ban)
    creative_approach = brain.get('creative_approach', 'light_twist')
    approach_guide = APPROACH_GUIDES.get(creative_approach, '')

    output.append(f"\n{sep}")
    output.append("STEP 1: 뇌 에이전트 판단")
    output.append(sep)
    output.append(f"판단: {brain.get('judgment', '')}")
    output.append(f"이유: {brain.get('reason', '')}")
    output.append(f"실행: {brain.get('action', '')}")
    output.append(f"creative_approach: {creative_approach}")
    output.append(f"approach_reason: {brain.get('approach_reason', '')}")

    print(f"판단: {brain.get('judgment', '')}")
    print(f"이유: {brain.get('reason', '')}")
    print(f"실행: {brain.get('action', '')}")
    print(f"creative_approach: {creative_approach}")
    print(f"approach_reason: {brain.get('approach_reason', '')}")

    # ── STEP 2: 영상 기획 뇌 (18케이스 기반) ──────────────
    print(f"\n{sep}")
    print("STEP 2: 영상 기획 뇌 — 18케이스 기반 기획")
    print(sep)

    draft = video_plan_brain(brain, brand_info, banned_str)
    print(draft)

    output.append(f"\n{sep}")
    output.append("STEP 2: Round 1 — 초안 생성")
    output.append(sep)
    output.append(draft)

    # ── STEP 3: 비판 + 재설계 ─────────────────────────────
    print(f"\n{sep}")
    print("STEP 3: Round 2 — 비판 + 재설계")
    print(sep)

    r2_system = ROUND2_SYSTEM.format(
        creative_approach=creative_approach,
        approach_guide=approach_guide,
        banned_patterns=banned_str
    )
    revised = claude_generate(r2_system, f"[브랜드 정보]\n{brand_info}\n\n[1차 기획안]\n{draft}")
    print(revised)

    output.append(f"\n{sep}")
    output.append("STEP 3: Round 2 — 비판 + 재설계")
    output.append(sep)
    output.append(revised)

    # ── STEP 4: 장면 완성 ─────────────────────────────────
    print(f"\n{sep}")
    print("STEP 4: Round 3 — 장면 완성")
    print(sep)

    r3 = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': ROUND3_SYSTEM},
            {'role': 'user', 'content': f"[브랜드 정보]\n{brand_info}\n\n[2차 재설계안]\n{revised}"}
        ],
        max_tokens=700,
        temperature=0.7
    )
    final = r3.choices[0].message.content
    print(final)

    output.append(f"\n{sep}")
    output.append("STEP 4: Round 3 — 장면 완성")
    output.append(sep)
    output.append(final)

    # ── 저장 ──────────────────────────────────────────────
    save_path = os.path.expanduser('~/Desktop/쇼츠_시뮬레이션_결과.txt')
    with open(save_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output))
    print(f"\n\n결과 저장: {save_path}")
    return brand_info


if __name__ == '__main__':
    brand_info = run()

    # ── 피드백 → 자동 케이스 추출 ─────────────────────────
    print("\n" + "=" * 60)
    print("나라면 이렇게 하겠다 (있으면 입력, 없으면 엔터):")
    try:
        feedback = input("> ").strip()
    except EOFError:
        feedback = ""

    if feedback:
        # Windows 인코딩 안전 처리
        safe_brand = brand_info.encode('utf-8', errors='ignore').decode('utf-8')
        safe_feedback = feedback.encode('utf-8', errors='ignore').decode('utf-8')
        result = extract_video_case_from_feedback(safe_feedback, safe_brand)
        if 'error' not in result:
            print(f"\n케이스 저장 완료 (#{result.get('id')})")
            print(f"업종: {result.get('industry')}")
            print(f"뻔한방향: {result.get('boring_direction')}")
            print(f"기획: {result.get('plan')}")
            print("\n→ 다음 기획부터 바로 반영됩니다.")
        else:
            print(f"추출 실패: {result['error']}")
