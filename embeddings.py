# -*- coding: utf-8 -*-
"""
벡터 임베딩 기반 패턴 검색
- OpenAI text-embedding-3-small 사용 (1536차원)
- pattern_embeddings 테이블에 저장/캐시
- numpy 행렬 연산으로 코사인 유사도 일괄 계산
"""
import json
import numpy as np

import db
from config_helper import get_config
from openai import OpenAI

_EMBED_MODEL = 'text-embedding-3-small'

# 메모리 캐시
_cache: dict = {}           # {pattern_id: list[float]}
_matrix: np.ndarray = None  # shape (N, 1536) — 정규화된 행렬
_matrix_ids: list = []      # matrix 행 순서와 대응하는 pattern_id 목록
_cache_loaded = False


def _client():
    return OpenAI(api_key=get_config().get('openai_api_key'))


def _build_matrix():
    """캐시 → numpy 정규화 행렬 빌드"""
    global _matrix, _matrix_ids
    if not _cache:
        _matrix = None
        _matrix_ids = []
        return
    _matrix_ids = list(_cache.keys())
    mat = np.array([_cache[pid] for pid in _matrix_ids], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    _matrix = mat / norms


def _load_cache():
    global _cache_loaded
    if _cache_loaded:
        return
    conn = db.get_conn()
    rows = db._fetchall(conn, 'SELECT pattern_id, embedding FROM pattern_embeddings')
    conn.close()
    for row in rows:
        _cache[row['pattern_id']] = json.loads(row['embedding'])
    _build_matrix()
    _cache_loaded = True


def _embed_texts(texts: list) -> list:
    """텍스트 배열 → 임베딩 배열 (배치 100개씩)"""
    cli = _client()
    results = []
    for i in range(0, len(texts), 100):
        batch = texts[i:i + 100]
        resp = cli.embeddings.create(model=_EMBED_MODEL, input=batch)
        results.extend([item.embedding for item in resp.data])
    return results


def ensure_embeddings() -> int:
    """전체 패턴의 임베딩이 DB에 있는지 확인, 없으면 생성. 생성한 개수 반환."""
    global _cache_loaded
    _cache_loaded = False
    _cache.clear()
    _load_cache()

    patterns_data = db.get_patterns()
    patterns = patterns_data.get('patterns', [])
    missing = [p for p in patterns if p['id'] not in _cache]

    if not missing:
        return 0

    print(f"[임베딩] {len(missing)}개 패턴 임베딩 생성 중...")
    texts = [p['rule'] for p in missing]
    embeddings = _embed_texts(texts)

    upsert_sql = (
        'INSERT INTO pattern_embeddings (pattern_id, embedding, model) VALUES (%s,%s,%s) '
        'ON CONFLICT (pattern_id) DO UPDATE SET embedding=EXCLUDED.embedding, model=EXCLUDED.model'
        if db._USE_PG else
        'INSERT OR REPLACE INTO pattern_embeddings (pattern_id, embedding, model) VALUES (?,?,?)'
    )

    conn = db.get_conn()
    for p, emb in zip(missing, embeddings):
        db._exec(conn, upsert_sql, [p['id'], json.dumps(emb), _EMBED_MODEL])
        _cache[p['id']] = emb
    conn.close()

    _build_matrix()
    print(f"[임베딩] 완료 ({len(missing)}개)")
    return len(missing)


def search_patterns(query: str, top_k: int = 250) -> list:
    """
    쿼리와 코사인 유사도가 높은 패턴 top_k개 반환.
    임베딩이 없으면 ensure_embeddings() 후 재시도.
    """
    _load_cache()

    if _matrix is None or len(_matrix_ids) == 0:
        ensure_embeddings()
        if _matrix is None or len(_matrix_ids) == 0:
            return []

    # 쿼리 임베딩
    cli = _client()
    resp = cli.embeddings.create(model=_EMBED_MODEL, input=[query])
    q_vec = np.array(resp.data[0].embedding, dtype=np.float32)
    q_norm = np.linalg.norm(q_vec)
    if q_norm > 0:
        q_vec /= q_norm

    # 행렬 × 벡터 → 유사도 배열
    sims = _matrix @ q_vec  # shape (N,)

    # top_k 인덱스
    k = min(top_k, len(_matrix_ids))
    top_indices = np.argpartition(sims, -k)[-k:]
    top_indices = top_indices[np.argsort(sims[top_indices])[::-1]]

    # pattern_id → 패턴 객체 매핑
    patterns_data = db.get_patterns()
    pattern_map = {p['id']: p for p in patterns_data.get('patterns', [])}

    result = []
    for idx in top_indices:
        pid = _matrix_ids[idx]
        if pid in pattern_map:
            result.append(pattern_map[pid])
    return result


def invalidate_pattern(pattern_id: int):
    """패턴 추가/수정/삭제 시 해당 패턴 임베딩 무효화"""
    global _cache_loaded
    _cache.pop(pattern_id, None)
    _cache_loaded = False  # 다음 호출 시 DB에서 재로드

    conn = db.get_conn()
    ph = db._ph()
    db._exec(conn, f'DELETE FROM pattern_embeddings WHERE pattern_id={ph}', [pattern_id])
    conn.close()


def get_embedding_stats() -> dict:
    """임베딩 현황 반환"""
    _load_cache()
    total_patterns = len(db.get_patterns().get('patterns', []))
    return {
        'embedded': len(_cache),
        'total': total_patterns,
        'coverage': round(len(_cache) / total_patterns * 100, 1) if total_patterns else 0
    }
