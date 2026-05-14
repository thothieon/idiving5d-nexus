# app/rag_retriever.py  ── RAG 向量召回模組（方案 A：Pure Python cosine similarity）
import os
import json
import math

from google import genai

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
EMBED_MODEL    = "text-embedding-004"
SIM_THRESHOLD  = 0.65   # 低於此分數的片段不使用


# ── Embedding ──────────────────────────────────────────────────

async def get_embedding(text: str) -> list[float] | None:
    """呼叫 Gemini text-embedding-004 取得向量（768 維）"""
    if not GOOGLE_API_KEY or not text.strip():
        return None
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        resp   = await client.aio.models.embed_content(
            model=EMBED_MODEL,
            contents=text,
        )
        return list(resp.embeddings[0].values)
    except Exception as e:
        print(f"[rag] embedding 失敗: {e}")
        return None


# ── Cosine Similarity ──────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot    = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── 召回 ───────────────────────────────────────────────────────

async def retrieve_relevant_chunks(
    conn,
    query_text: str,
    top_k: int = 3,
) -> list[dict]:
    """
    針對 query_text 取得最相關的 top_k 知識片段。
    回傳 list of dict：{id, title, content, score}
    """
    query_emb = await get_embedding(query_text)
    if not query_emb:
        return []

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, title, content, embedding FROM knowledge_chunks "
            "WHERE is_active=1 AND embedding IS NOT NULL"
        )
        rows = await cur.fetchall()

    if not rows:
        return []

    scored = []
    for row in rows:
        try:
            emb = row["embedding"]
            if isinstance(emb, str):
                emb = json.loads(emb)
            if not emb:
                continue
            score = cosine_similarity(query_emb, emb)
            if score >= SIM_THRESHOLD:
                scored.append({
                    "id":      row["id"],
                    "title":   row["title"],
                    "content": row["content"],
                    "score":   round(score, 4),
                })
        except Exception:
            continue

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def format_rag_context(chunks: list[dict]) -> str:
    """將召回的片段格式化成可插入 prompt 的文字段落"""
    if not chunks:
        return ""
    lines = ["=== 知識庫參考資料（請優先依此回覆客戶）==="]
    for c in chunks:
        lines.append(f"【{c['title']}】\n{c['content']}")
    lines.append("=== 參考資料結束 ===")
    return "\n".join(lines)
