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

[번역 원칙 — 이걸 어기면 실패]
- 전략을 설명하는 장면이면 실패다.
- 논리적으로 맞는 장면도 실패다. "아 그렇구나"가 나오면 실패. "ㅋㅋ" 또는 "어?!"가 나와야 성공.
- 반드시 아래 웃음 메커니즘 중 하나를 써라.

[웃음 메커니즘 4가지 — 반드시 하나를 골라 적용해라]
1. 장르 이식: 완전히 다른 장르/시대 맥락에 브랜드를 이식. 시대극, 스포츠 중계, 법정, 자연 다큐, SF 등
   예: 카센터 → 시대극 "환자가 있소!!" / 웨딩 → 스카이캐슬 과외 선생님 패러디
2. 황당한 비유: 추상적 개념을 예상 밖의 물리적 장면으로 번역
   예: 세금 낭비 → 수돗꼭지에서 돈이 콸콸 샘 / 대출 압박 → 드롭킥으로 날려버림
3. 완전 예상 역전: 당연히 이럴 거라 생각했는데 정반대. 첫 3초에 "어? 이게 맞나?"
   예: 헬스장 → 건장한 사람 말고 노인이 앞서감 / 학원 → 맨날 놀고 자는데 합격
4. 과잉 반응/과장: 상황이 황당할 정도로 과장됨. 등장인물 반응이 극단적으로 드라마틱
   예: 부동산 → 직원이 전화 폭주에 으아아아 소리 지름 / 맛집 → 커플이 격하게 싸우는데 케이크에 포크 2개

[실제 번역 사례]
전략: 경쟁/혼잡을 역전 / 메커니즘: 과잉반응 / 장면: 직원이 전화 폭주에 으아아아 소리 지르며 집 보러 사람들이 우르르 따라옴
전략: 두려운 장면으로 역전 / 메커니즘: 완전 예상 역전 / 장면: 맨날 놀고 잠만 자는데 서울대 합격
전략: 추상 손해 각인 / 메커니즘: 황당한 비유 / 장면: 수돗꼭지에서 돈이 콸콸 새는데 수리기사가 자꾸 실패
전략: 예상 불가 역전 / 메커니즘: 완전 예상 역전 / 장면: 몸 좋은 젊은이 헉헉대는데 노인이 훨씬 빠르게 앞서감
전략: 타겟의 적 제거 / 메커니즘: 황당한 비유 / 장면: 대출 압박 인물 앞 절규 → 상품이 달려와 드롭킥
전략: 전문성 리빌 / 메커니즘: 장르 이식 / 장면: 시대극 느낌으로 "환자가 있소!!" 울먹이며 외치다 정비사가 뚝딱 고침
전략: 제품 경쟁력 증명 / 메커니즘: 과잉반응 / 장면: 커플이 격하게 싸우는데 케이크 마지막 조각에 포크 2개 꽂혀있음

---

[출력 형식 — JSON으로]
{{
  "scene_line": "장면 한 줄 (시각적이고 구체적으로, 반드시 웃기거나 충격적인 장면)",
  "mechanism": "사용한 웃음 메커니즘 (4가지 중 하나)",
  "scene_reason": "왜 이 장면인가 — 어떤 감정(웃음/충격/공감)이 터지는지 한 줄"
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


VIDEO_BRAIN_SYSTEM = """
너는 유튜브 쇼츠 영상 기획 전문가다.
아래 18개 실제 기획 사례를 보고, 동일한 사고방식으로 이 브랜드의 영상을 기획해라.

[핵심 기획 로직]
1. 타겟의 핵심 불안/욕망을 찾아라
2. 이 업종에서 남들이 다 하는 뻔한 방향을 파악해라
3. 그걸 가장 극적으로 비트는 장면을 3초 안에 설계해라
→ 반드시 시청자가 웃거나(ㅋㅋ) 놀라거나(어?!) 공감 폭발하는 방식으로

[뻔한 방향을 어떻게 비트는가 — 18개 실제 사례]

[법무법인]
뻔한방향: 문제 제시 + 상담 CTA
기획: 법정, 긴장감 속 변호사 완벽한 변론 → 판사 무죄 선고 → 페이드아웃

[뷰티클리닉 - 20대]
뻔한방향: 시술 전후 비교
기획: 예쁜 여성이 걸어가는데 지나치는 남자들이 다 뒤돌아봄 → OO클리닉

[뷰티클리닉 - 중장년]
뻔한방향: 시술 전후 비교
기획: 20대보다 탱탱한 피부의 중장년 여성 → 또래 역행 장면

[헬스장 - 소형]
뻔한방향: 몸매 변화 전후
기획: 대형 헬스장 앞에서 커플이 줄 서며 "여기 진짜 맛집인가봐" 대화 → 시점 전환, 소형 헬스장 1:1 PT 장면

[헬스장 - 대형]
뻔한방향: 몸매 변화 전후
기획: 사람들이 우르르 몰려오는 대형 헬스장 → 소셜 프루프로 증명

[식당/카페 - 디저트]
뻔한방향: 음식 클로즈업 + 맛있겠다
기획: 커플이 격하게 싸우는데 사이로 케이크 마지막 조각에 포크 2개 꽂혀있음 → "10년차 연인도 싸우게 만드는 케이크" → OO카페

[부동산]
뻔한방향: 좋은 집 소개 + 문의
기획: 직원이 전화 폭주에 으아아아 소리 지르며, 집 보러 사람들이 우르르 뒤따라옴 → "대입보다 경쟁률 높은 부동산" → OO부동산

[학원]
뻔한방향: 합격 후기 + 성적 수치
기획: 주인공이 맨날 밖에서 놀고 수업 때 잠만 자는데 → 갑자기 눈이 활활 불타며 서울대 합격 → "공부는 재밌어야 한다" → OO학원

[펫샵/동물병원]
뻔한방향: 귀여운 동물 + 전문 케어
기획: 젊은 여성 주변에 새끼 강아지들이 뛰어오고 재롱 피우는데 → 꿈에서 깨듯 화면 전환, 여성이 벌떡 일어남 → "세상 귀여운 강아지는 모두 여기에" → OO펫샵

[인테리어/리모델링]
뻔한방향: 시공 전후 + 견적 문의
기획: 주부가 친구 초대해 집 보여줌, 친구 부러워하며 "1억 썼어?" → 반대로 그 친구가 초대하니 처음 주부가 말 못하고 허탈 → "나는 OO인테리어에서 5천만원에 이렇게 했어!"

[카이로프랙틱/정형외과]
뻔한방향: 통증 호소 + 치료 후 개선
기획: 젊고 몸 좋은 사람이 헉헉거리며 뛰는데 → 옆에서 노인이 훨씬 빠르게 꼿꼿하게 앞서감 → "통증 100% 완치" → OO정형외과

[웨딩/스드메]
뻔한방향: 아름다운 웨딩 + 패키지 문의
기획: 스카이캐슬 과외 선생님 "전적으로 절 믿으셔야 합니다" 장면 오마주 → 웨딩 플래너가 똑같은 포즈로

[세무사/회계사]
뻔한방향: 절세 팁 + 상담
기획: 수돗꼭지에서 물이 나오다가 점점 돈으로 바뀌며 콸콸 새는데 → 수리기사가 땀 흘리며 고치려다 자꾸 새기만 함 → 다른 수리기사가 밀치고 한번에 탁 고치며 정장으로 전환

[보험]
뻔한방향: 위험 상황 + 가입 유도
기획: 끼이익 차 사고 소리 → 화면 분할, 한쪽 컬러로 보험 있어서 수술+재활 완료, 한쪽 흑백으로 가족들이 힘들어하고 의사 선고 → 가족 욺

[이커머스/온라인쇼핑몰]
뻔한방향: 상품 + 할인 강조
기획: 두두둥 어두웠다 밝아지며 드라마틱 리빌 → 모델이 상품 실제로 사용하는 장면 위주, 설명 최소화

[SaaS/IT솔루션]
뻔한방향: 기능 설명 + 데모 요청
기획: 인하우스 마케터들이 엄청 바삐 우왕좌왕 → 화면 전환, 마케터 1명이 SaaS로 훨씬 빠르게 처리

[프랜차이즈 창업]
뻔한방향: 성공 사례 + 설명회
기획: 손님 없는 매장에서 사장이 한숨 → 갑자기 사람들이 들어와 매장 싹 바꿔버림 → 손님 몰림 → OO치킨

[금융/대출]
뻔한방향: 금리 비교 + 신청 유도
기획: 주인공이 대출 상징 인물 앞에서 절규하며 주저앉아 욺 → 우리 상품이 달려와서 드롭킥으로 차버림 → 주인공 일으켜서 안아줌

[카센터/자동차정비]
뻔한방향: 수리 전후 + 친절한 정비사
기획: 옛날 시대극 느낌으로 웃기게 생긴 주인공이 "환자가 있소!! 아무도 없소?!!" 울먹이며 외치는데 → 점점 멀어지며 리어카 등장 → "정녕 아무도 없는거요!!" → 정비사가 뚝딱 고침 → "리어카도 당일 수리하는 OO카센터"

[이사/이삿짐센터]
뻔한방향: 이사 과정 편리함 + 파손 없음 강조
기획: 올림픽 컬링 중계처럼 연출 → 상반신만 보이는 선수가 극도로 진지하게 자세 잡고 스톤 놓는 동작 → 놓는 순간 냉장고가 컬링 스톤처럼 슉 미끄러져 딱 제자리에 들어옴 → 아나운서 감탄 "완벽한 배치입니다!!" → "이사도 국가대표급으로"

---

[뇌 에이전트 전략 방향]
{brain_judgment}

[소거 목록 — 이 패턴이 보이면 실패]
{banned_patterns}

[출력 형식]
뻔한방향:
비틀기방향:
영상기획:
"""


def _build_cases_str(cases: list) -> str:
    """DB 케이스 목록 → 프롬프트 문자열"""
    lines = []
    for c in cases:
        lines.append(f"\n[{c['industry']}]")
        lines.append(f"뻔한방향: {c['boring_direction']}")
        lines.append(f"기획: {c['plan']}")
    return "\n".join(lines)


def video_plan_brain(brain_output: dict, brand_info: str, banned_patterns: str) -> str:
    """
    DB 케이스 기반 영상 기획 뇌.
    뇌 에이전트 전략 방향을 받아서 창의적인 영상 기획을 생성.
    케이스를 DB에서 읽어오고, 없으면 VIDEO_BRAIN_SYSTEM 하드코딩으로 폴백.
    """
    import anthropic as _anthropic
    import db as _db
    from config_helper import get_config as _get_config

    cfg = _get_config()
    claude_client = _anthropic.Anthropic(api_key=cfg.get('anthropic_api_key'))

    # DB 시드 및 케이스 로드
    _db.seed_video_cases()
    cases = _db.get_approved_video_cases()

    if cases:
        cases_str = _build_cases_str(cases)
        system_prompt = VIDEO_BRAIN_SYSTEM.split('[뻔한 방향을 어떻게 비트는가')[0] + \
            f"[뻔한 방향을 어떻게 비트는가 — {len(cases)}개 실제 사례]\n" + \
            cases_str + \
            "\n\n---\n\n[뇌 에이전트 전략 방향]\n{brain_judgment}\n\n[소거 목록 — 이 패턴이 보이면 실패]\n{banned_patterns}\n\n[출력 형식]\n뻔한방향:\n비틀기방향:\n영상기획:"
    else:
        system_prompt = VIDEO_BRAIN_SYSTEM

    brain_summary = f"""판단: {brain_output.get('judgment', '')}
이유: {brain_output.get('reason', '')}
실행 힌트: {brain_output.get('action', '')}"""

    system_prompt = system_prompt.format(
        brain_judgment=brain_summary,
        banned_patterns=banned_patterns,
    )

    resp = claude_client.messages.create(
        model='claude-opus-4-6',
        max_tokens=8000,
        thinking={'type': 'adaptive'},
        messages=[{'role': 'user', 'content': system_prompt + "\n\n" + brand_info}]
    )
    for block in resp.content:
        if block.type == 'text':
            return block.text
    return ''


def extract_video_case_from_feedback(feedback: str, brand_info: str) -> dict:
    """
    사용자 피드백("나라면 이렇게")에서 영상 기획 케이스를 자동 추출.
    추출된 케이스는 DB에 pending 상태로 저장.
    Returns: {id, industry, boring_direction, plan}
    """
    import db as _db
    client = OpenAI(api_key=get_config().get('openai_api_key'))

    prompt = f"""사용자가 유튜브 쇼츠 기획에 대해 피드백을 남겼다.
이 피드백에서 영상 기획 케이스를 추출해라.

[브랜드 정보]
{brand_info}

[사용자 피드백]
{feedback}

[추출 기준]
- industry: 브랜드 업종
- boring_direction: 이 업종에서 흔히 하는 뻔한 방향 (한 줄)
- plan: 사용자가 제안한 창의적 기획 (구체적으로, 장면 흐름 포함)

JSON으로 반환:
{{"industry": "업종", "boring_direction": "뻔한 방향", "plan": "기획 내용"}}"""

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[{'role': 'user', 'content': prompt}],
        max_tokens=400,
        temperature=0.2,
        response_format={'type': 'json_object'}
    )

    try:
        result = json.loads(response.choices[0].message.content)
        case_id = _db.add_video_case(
            industry=result.get('industry', ''),
            boring_direction=result.get('boring_direction', ''),
            plan=result.get('plan', ''),
            source='extracted',
            status='pending'
        )
        result['id'] = case_id
        return result
    except Exception as e:
        return {'error': str(e)}


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
