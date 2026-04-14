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
  "judgment": "이 고객사 쇼츠의 핵심 방향 한 줄",
  "reason": "왜 이 방향인가 — 타겟 심리 + 경쟁 구도 기반 2-3줄",
  "action": "지금 만들 영상 1편 — 첫 3초 훅 / 중간 구성 / 마지막 행동 유도까지 구체적으로",
  "creative_approach": "strong_twist 또는 light_twist 또는 product_focus",
  "approach_reason": "왜 이 approach인가 — 위 패턴 중 어떤 원칙이 발동됐는지"
}}
"""


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
