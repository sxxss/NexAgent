"""Knowledge-base retrieval evaluation helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from nexagent.knowledge.retriever import HybridRetriever


@dataclass
class QATestCase:
    question: str
    expected: str
    relevant_file_ids: list[str] = field(default_factory=list)


@dataclass
class RetrievalConfig:
    mode: str = "hybrid"
    top_k: int = 10
    recall_top_k: int | None = None
    final_top_k: int | None = None
    similarity_threshold: float | None = None
    vector_weight: float | None = None
    keyword_weight: float | None = None
    use_reranker: bool | None = None
    reranker_model: str = ""


@dataclass
class EvaluationReport:
    total: int
    recall: float
    precision: float
    mrr: float
    ndcg: float
    details: list[dict] = field(default_factory=list)


class KnowledgeBaseEvaluator:
    """Evaluate retrieval quality against simple QA expectations."""

    def __init__(self, retriever: HybridRetriever | None = None) -> None:
        self.retriever = retriever or HybridRetriever()

    async def evaluate(
        self,
        kb_id: str,
        test_cases: list[QATestCase],
        retrieval_config: RetrievalConfig | None = None,
    ) -> EvaluationReport:
        cfg = retrieval_config or RetrievalConfig()
        details: list[dict] = []
        recall_hits = 0
        precision_sum = 0.0
        reciprocal_sum = 0.0
        ndcg_sum = 0.0

        for case in test_cases:
            retrieval_kwargs = {
                key: value
                for key, value in cfg.__dict__.items()
                if key not in {"mode", "top_k"} and value is not None and value != ""
            }
            chunks = await self.retriever.retrieve(
                case.question,
                [kb_id],
                mode=cfg.mode,  # type: ignore[arg-type]
                top_k=cfg.top_k,
                **retrieval_kwargs,
            )
            expected = case.expected.lower()
            relevant_files = set(case.relevant_file_ids)
            hit_positions: list[int] = []
            for index, chunk in enumerate(chunks, start=1):
                text_hit = expected and expected in chunk.content.lower()
                file_hit = bool(relevant_files and chunk.file_id in relevant_files)
                if text_hit or file_hit:
                    hit_positions.append(index)

            hit_count = len(hit_positions)
            if hit_count:
                recall_hits += 1
                reciprocal_sum += 1 / hit_positions[0]
                ndcg_sum += _ndcg(hit_positions, len(chunks))
            precision_sum += hit_count / max(len(chunks), 1)
            details.append(
                {
                    "question": case.question,
                    "hit": bool(hit_positions),
                    "first_hit_rank": hit_positions[0] if hit_positions else None,
                    "retrieved": len(chunks),
                }
            )

        total = len(test_cases)
        if total == 0:
            return EvaluationReport(total=0, recall=0.0, precision=0.0, mrr=0.0, ndcg=0.0, details=[])
        return EvaluationReport(
            total=total,
            recall=recall_hits / total,
            precision=precision_sum / total,
            mrr=reciprocal_sum / total,
            ndcg=ndcg_sum / total,
            details=details,
        )


def _ndcg(hit_positions: list[int], retrieved_count: int) -> float:
    import math

    if not hit_positions or retrieved_count <= 0:
        return 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in hit_positions)
    ideal_hits = min(len(hit_positions), retrieved_count)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0
