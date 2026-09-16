"""Sàn số chunk tối thiểu khi lọc theo ngưỡng rerank.

Bối cảnh: điểm của Cohere rerank-multilingual-v3.0 trên corpus tiếng Việt phân
bố lưỡng cực — khớp tốt thì ~0,99, không khớp thì ~0,01. Ngưỡng
NEXUSRAG_MIN_RELEVANCE_SCORE nằm giữa hai cụm nên thường chỉ đúng một chunk
vượt ngưỡng. Một chunk là context quá mỏng, và nếu chunk đó lệch chủ đề thì
câu trả lời hỏng hẳn dù chunk đúng đang nằm ngay dưới ngưỡng.
"""
from __future__ import annotations

from app.services.deep_retriever import MIN_CONTEXT_CHUNKS, DeepRetriever
from app.services.models.parsed_document import Citation, EnrichedChunk
from app.services.reranker import RerankResult


class _StubReranker:
    """Trả về đúng bảng điểm đã dựng sẵn, theo thứ tự giảm dần."""

    def __init__(self, scores: list[float]):
        self._scores = scores

    def rerank(self, query, documents, top_k=None, min_score=None):
        results = [
            RerankResult(index=i, score=score, text=documents[i])
            for i, score in enumerate(self._scores)
        ]
        results.sort(key=lambda r: r.score, reverse=True)
        if top_k is not None:
            results = results[:top_k]
        if min_score is not None:
            results = [r for r in results if r.score >= min_score]
        return results


def _retriever(scores: list[float]) -> DeepRetriever:
    return DeepRetriever(
        workspace_id=1,
        kg_service=None,
        vector_store=object(),
        embedder=object(),
        db=None,
        reranker=_StubReranker(scores),
    )


def _chunks(n: int) -> tuple[list[EnrichedChunk], list[Citation]]:
    chunks = [
        EnrichedChunk(
            content=f"noi dung {i}",
            chunk_index=i,
            source_file="hop-dong.docx",
            document_id=1,
            page_no=1,
        )
        for i in range(n)
    ]
    citations = [
        Citation(source_file="hop-dong.docx", document_id=1, page_no=1) for _ in range(n)
    ]
    return chunks, citations


def test_rerank_chunks_one_chunk_above_threshold_tops_up_to_minimum():
    # 1 chunk vượt ngưỡng 0.15, phần còn lại ngay dưới — đúng ca đã làm hỏng
    # câu hỏi về điều khoản thanh toán trong hợp đồng.
    chunks, citations = _chunks(5)
    retriever = _retriever([0.163, 0.118, 0.065, 0.022, 0.010])

    kept, kept_citations = retriever._rerank_chunks("q", chunks, citations, top_k=5)

    assert len(kept) == MIN_CONTEXT_CHUNKS
    assert len(kept_citations) == MIN_CONTEXT_CHUNKS
    # Phải là 3 chunk điểm cao nhất, theo đúng thứ hạng của reranker.
    assert [c.chunk_index for c in kept] == [0, 1, 2]


def test_rerank_chunks_no_chunk_above_threshold_still_returns_minimum():
    chunks, citations = _chunks(5)
    retriever = _retriever([0.032, 0.011, 0.008, 0.004, 0.001])

    kept, _ = retriever._rerank_chunks("q", chunks, citations, top_k=5)

    assert len(kept) == MIN_CONTEXT_CHUNKS
    assert [c.chunk_index for c in kept] == [0, 1, 2]


def test_rerank_chunks_keeps_every_chunk_above_threshold():
    # Reranker tự tin: giữ nguyên tất cả, sàn không được cắt bớt.
    chunks, citations = _chunks(5)
    retriever = _retriever([0.99, 0.87, 0.64, 0.48, 0.31])

    kept, _ = retriever._rerank_chunks("q", chunks, citations, top_k=5)

    assert len(kept) == 5


def test_rerank_chunks_fewer_candidates_than_minimum_returns_all():
    chunks, citations = _chunks(2)
    retriever = _retriever([0.09, 0.02])

    kept, _ = retriever._rerank_chunks("q", chunks, citations, top_k=5)

    assert len(kept) == 2


def test_rerank_chunks_empty_input_returns_empty():
    retriever = _retriever([])

    assert retriever._rerank_chunks("q", [], [], top_k=5) == ([], [])
