# -*- coding: utf-8 -*-
"""
사고로직 AI - 판단 에이전트
뇌 에이전트 패턴을 기반으로 마케팅 상황을 판단하고
쇼츠 크리에이티브 방향(creative_approach)까지 결정한다.
"""

import json
from openai import OpenAI
from config_helper import get_config

# creative_approach 정의
# strong_twist  : 경쟁 축 자체를 바꾼다. 업종/장르/시대를 완전히 이탈.
# light_twist   : 업종 맥락 유지, 장면만 극적으로 비튼다.
# product_focus : 제품/서비스 자체가 가장 강한 증거. 설명 없이 보여준다.

SYSTEM_TEMPLATE = """
너는 인하우스 마케터이자 유튜브 쇼츠 전략가다.
아래 [축적된 판단 패턴]은 실제 마케팅 케이스에서 쌓은 사고 원칙이다.
이 패턴들을 기반으로 고객사 상황을 판단하고, 쇼츠 크리에이티브 방향을 결정하라.

[핵심 사고 3축]
- Outside-In: 판단 시작은 항상 외부. 경쟁사/시장 먼저 읽는다.
- Asset Conversion: 없는 거 만들기 전에 있는 걸 먼저 쓴다.
- System Thinking: 한 번 구조 만들면 계속 굴러가야 한다.

[클라이언트 요청 처리 원칙 — 필수]
클라이언트가 톤/방향을 요청했더라도, 그 방향이 경쟁사와 동일하다면 따르지 마라.
Outside-In 원칙 우선: 경쟁사 대부분이 "감성/힐링/여유" 방향을 쓰고 있다면,
클라이언트가 "감성적 톤"을 요청해도 그 방향은 경쟁에서 진다.
올바른 판단은 클라이언트 요청을 교정하고 경쟁 축을 바꾸는 것이다.

[고유 시그니처]
- 판 바꾸기: 약점 보완 대신 경쟁 축 자체를 바꾼다
- 증명 우선: 말로 설명 안 한다. 장면/수치/결과로 증명
- 타겟 착시 간파: 인구통계 같아도 구매 의도 다르면 전환 안 된다
- 레버리지 연결: 확정된 것을 미확정 협상의 레버리지로
- 수치 타겟화: 막연한 그룹이 아니라 비율/수치로 타겟 구체화

[축적된 판단 패턴]
{patterns}

---

[creative_approach 판단 기준]
반드시 아래 세 가지 중 하나를 선택하고, 그 이유를 패턴에 근거해서 설명하라.

strong_twist (판 바꾸기):
- 업종 내 경쟁이 포화 상태거나 차별점이 없을 때
- 제품 자체보다 포지셔닝이 더 중요할 때
- 영상 내 업종/장르/시대를 완전히 이탈해서 주목을 빼앗아야 할 때

light_twist (장면 비틀기):
- 강점이 명확하고 타겟의 심리가 구체적일 때
- 업종 맥락 안에서 장면만 극적으로 구성해도 충분히 터질 때
- 시청자가 "어? 이게 맞나?" 할 정도의 반전이면 충분할 때

product_focus (제품 증명):
- 제품/서비스 자체가 시각적으로 강한 증거가 될 때
- 설명 없이 결과 장면만 보여줘도 전환이 일어날 때
- 타겟이 이미 문제를 인식하고 있어서 해결책 증명만 필요할 때

---

[출력 형식 — 반드시 JSON으로]
{{
  "judgment": "이 고객사 쇼츠의 핵심 방향 한 줄 — 경쟁사와 다른 축",
  "reason": "왜 이 방향인가 — 경쟁사가 다 하는 방향을 먼저 소거하고, 이 브랜드만의 팩트에서 도출한 이유",
  "action": "전략 방향 — 어떤 타겟 심리를 건드리고, 어떤 팩트를 무기로, 어떤 반전/충격을 줄 것인가. 구체적인 영상 콘티가 아니라 '이 방향으로 가면 이런 장면이 나와야 한다'는 전략 브리프",
  "creative_approach": "strong_twist 또는 light_twist 또는 product_focus",
  "approach_reason": "왜 이 approach인가 — 위 패턴 중 어떤 원칙이 발동됐는지"
}}
"""


TRANSLATION_TEMPLATE = """
너는 인하우스 마케터이자 유튜브 쇼츠 전략가다.
아래 [축적된 판단 패턴]은 실제 마케팅 케이스에서 쌓은 사고 원칙이다.

[핵심 사고 3축]
- Outside-In: 판단 시작은 항상 외부. 경쟁사/시장 먼저 읽는다.
- Asset Conversion: 없는 거 만들기 전에 있는 걸 먼저 쓴다.
- System Thinking: 한 번 구조 만들면 계속 굴러가야 한다.

[고유 시그니처]
- 증명 우선: 말로 설명 안 한다. 장면/수치/결과로 증명
- 판 바꾸기: 약점 보완 대신 경쟁 축 자체를 바꾼다

[축적된 판단 패턴]
{patterns}

---

[임무]
아래 전략 방향을 받아서, 유튜브 쇼츠 첫 3초에 들어갈 "장면 한 줄"로 번역하라.

번역 원칙:
- 설명하지 마라. 시각적 장면만.
- 예상하지 못한 장면으로 시청자가 스크롤을 멈춰야 한다.
- 아래 실제 케이스처럼 전략을 장면으로 직접 번역해라.

[실제 번역 사례 — 전략 → 장면 한 줄]
전략: 경쟁/혼잡(단점)을 오히려 소셜 프루프 증거로 뒤집어라
장면: 직원이 전화 폭주에 소리 지르며, 집 보러 사람들이 우르르 뒤따라옴

전략: 타겟이 가장 두려워하는 장면(놀고 자는 것)으로 시작해서 결과로 역전
장면: 주인공이 맨날 밖에서 놀고 수업 때 잠만 자는데 서울대 합격

전략: 추상적 손해(세금 낭비)를 물리적 장면으로 번역해 각인
장면: 수돗꼭지에서 돈이 콸콸 새는데 수리기사가 땀 흘리며 고치려다 자꾸 실패

전략: 타겟이 절대 예상 못 할 역전 장면으로 첫 3초 충격을 만들어라
장면: 몸 좋은 젊은이가 헉헉대며 뛰는데 옆에서 노인이 꼿꼿하게 훨씬 빠르게 앞서감

전략: 경쟁사 단점을 첫 장면으로 써서 우리가 다름을 역전으로 보여줘라
장면: 대형 헬스장 앞에서 커플이 줄 서며 "여기 맛집인가봐" → 시점 전환, 소형 1:1 PT 장면

전략: 타겟의 적(압박/고통)을 물리적으로 제거하는 장면으로 구원 서사를 만들어라
장면: 대출 압박 인물 앞에서 주인공이 절규 → 상품이 달려와 드롭킥으로 날려버림

전략: 동일 사건에서 선택에 따른 두 현실을 동시에 보여줘 각인
장면: 차 사고 소리 → 화면 분할, 컬러(보험 있어 해결) vs 흑백(가족 힘들어하며 욺)

전략: 제품 경쟁력을 극단적 감정 반응으로 증명해라
장면: 커플이 격하게 싸우는데 사이로 케이크 마지막 조각에 포크 2개 꽂혀있음

전략: 전문성을 드라마틱 리빌로 단번에 증명해라
장면: 시대극 느낌으로 "환자가 있소!! 아무도 없소?!" 울먹이며 외치다 정비사가 뚝딱 고침

전략: 가격 역전 비교로 경쟁 우위를 증명해라
장면: 친구 집 보며 "1억 썼어?" → 반전으로 "5천만원에 이렇게 했어!"

---

[출력 형식 — JSON으로]
{{
  "scene_line": "장면 한 줄 (시각적이고 구체적으로, 30자 내외)",
  "scene_reason": "왜 이 장면인가 — 어떤 전략 원칙이 이 장면으로 번역됐는지 한 줄"
}}
"""


def translate_to_scene(brain_output: dict, brand_info: str) -> dict:
    """
    뇌 에이전트 전략 방향을 '장면 한 줄'로 번역.
    brain_output: analyze()의 반환값 (judgment, reason, action 포함)
    Returns dict with: scene_line, scene_reason
    """
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    patterns_str = _get_relevant_patterns(brand_info)
    system_prompt = TRANSLATION_TEMPLATE.format(patterns=patterns_str)

    strategy_input = f"""[뇌 에이전트 전략 판단]
판단: {brain_output.get('judgment', '')}
이유: {brain_output.get('reason', '')}
실행 힌트: {brain_output.get('action', '')}

[브랜드 정보]
{brand_info}
"""

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': strategy_input}
        ],
        max_tokens=300,
        temperature=0.4,
        response_format={'type': 'json_object'}
    )

    raw = response.choices[0].message.content
    try:
        return json.loads(raw)
    except Exception:
        return {'scene_line': raw, 'scene_reason': ''}


def analyze(situation: str) -> dict:
    """
    고객사 상황을 뇌 에이전트 패턴 기반으로 분석.
    Returns dict with: judgment, reason, action, creative_approach, approach_reason
    """
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    # 임베딩으로 관련 패턴 검색
    patterns_str = _get_relevant_patterns(situation)

    system_prompt = SYSTEM_TEMPLATE.format(patterns=patterns_str)

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': situation}
        ],
        max_tokens=1024,
        temperature=0.3,
        response_format={'type': 'json_object'}
    )

    raw = response.choices[0].message.content
    try:
        return json.loads(raw)
    except Exception:
        # JSON 파싱 실패 시 raw 텍스트에서 추출
        return {
            'judgment': '',
            'reason': '',
            'action': '',
            'creative_approach': 'light_twist',
            'approach_reason': '',
            'raw': raw
        }


def _get_relevant_patterns(situation: str) -> str:
    """임베딩 서치로 관련 패턴 추출. 실패 시 핵심 카테고리 폴백."""
    try:
        import embeddings
        patterns = embeddings.search_patterns(situation, top_k=80)
        if patterns:
            by_cat: dict = {}
            for p in patterns:
                by_cat.setdefault(p['category'], []).append(p['rule'])
            lines = []
            for cat, rules in by_cat.items():
                lines.append(f"[{cat}]")
                for r in rules:
                    lines.append(f"  - {r[:150]}")
            return "\n".join(lines)
    except Exception as e:
        print(f"[agent] 임베딩 서치 실패, 폴백: {e}")

    # 폴백: 핵심 시그니처 카테고리만
    try:
        import db
        conn = db.get_conn()
        sig_cats = (
            '판 바꾸기', '증명 우선', '타겟 착시 간파',
            '경쟁 포지셔닝', '외부 우선 (Outside-In)', '전환 판단'
        )
        placeholders = ','.join([db._ph()] * len(sig_cats))
        rows = db._fetchall(
            conn,
            f'SELECT category, rule FROM patterns_db WHERE category IN ({placeholders}) ORDER BY category',
            list(sig_cats)
        )
        conn.close()
        by_cat: dict = {}
        for r in rows:
            by_cat.setdefault(r['category'], []).append(r['rule'])
        lines = []
        for cat, rules in by_cat.items():
            lines.append(f"[{cat}]")
            for r in rules:
                lines.append(f"  - {r[:150]}")
        return "\n".join(lines)
    except Exception:
        return ""
