from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PASS1_SCHEMA_VERSION = "edc_v1"


ChunkType = Literal["text", "table", "mixed"]
FactDecision = Literal["keep", "rescue", "drop"]


@dataclass
class TemporalContext:
    filing_year: int = 2025
    fiscal_year_end: str = "December"
    primary_period: str = "FY2025"
    prior_period: str = "FY2024"
    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TemporalContext":
        return cls(**(data or {}))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Section:
    section_title: str
    parent_section: str
    page_start: int | None
    page_end: int | None
    doc_id: str = ""
    section_id: str = ""
    text_blocks: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    content: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Section":
        return cls(
            doc_id=data.get("doc_id", ""),
            section_id=data.get("section_id", ""),
            section_title=data.get("section_title", ""),
            parent_section=data.get("parent_section", ""),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
            text_blocks=data.get("text_blocks", []),
            tables=data.get("tables", []),
            content=data.get("content", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Chunk:
    doc_id: str
    section_id: str
    chunk_id: str
    prev_chunk_id: str | None
    next_chunk_id: str | None
    section_title: str
    parent_section: str
    page_start: int | None
    page_end: int | None
    chunk_type: ChunkType
    content: str
    char_count: int
    token_estimate: int
    temporal_context: TemporalContext

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Chunk":
        return cls(
            doc_id=data.get("doc_id", ""),
            section_id=data.get("section_id", ""),
            chunk_id=data.get("chunk_id", ""),
            prev_chunk_id=data.get("prev_chunk_id"),
            next_chunk_id=data.get("next_chunk_id"),
            section_title=data.get("section_title", ""),
            parent_section=data.get("parent_section", ""),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
            chunk_type=data.get("chunk_type", "text"),
            content=data.get("content", ""),
            char_count=data.get("char_count", 0),
            token_estimate=data.get("token_estimate", 0),
            temporal_context=TemporalContext.from_dict(data.get("temporal_context")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["temporal_context"] = self.temporal_context.to_dict()
        return data


@dataclass
class ExtractedFact:
    fact_id: str
    doc_id: str
    section_id: str
    chunk_id: str
    prev_chunk_id: str | None
    next_chunk_id: str | None
    section_title: str
    parent_section: str
    page_start: int | None
    page_end: int | None
    temporal_context: TemporalContext
    decision: FactDecision | str
    metric: str = ""
    value: Any = None
    unit: str = ""
    period: str = ""
    period_start: str | None = None
    period_end: str | None = None
    period_type: str = "unknown"
    period_confidence: str = ""
    fact_type: str = "measurement"
    entity: str = ""
    segment: str = ""
    evidence: str = ""
    metric_definition: str | None = None
    baseline_year: str | None = None
    confidence: float | None = None
    rescue_pass: bool = False
    rescue_result: str = ""
    duplicate_chunk_ids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["temporal_context"] = self.temporal_context.to_dict()
        return data


@dataclass
class NormalizedFact:
    fact_id: str
    source_fact_id: str
    doc_id: str
    section_id: str
    chunk_id: str
    prev_chunk_id: str | None
    next_chunk_id: str | None
    section_title: str
    parent_section: str
    page_start: int | None
    page_end: int | None
    temporal_context: TemporalContext
    decision: FactDecision | str
    metric: str = ""
    normalized_metric: str = ""
    value: float | None = None
    unit: str = ""
    scale: str = ""
    currency: str = ""
    period: str = ""
    period_start: str | None = None
    period_end: str | None = None
    period_type: str = "unknown"
    period_confidence: str = ""
    fact_type: str = "measurement"
    fiscal_year: int | None = None
    entity: str = ""
    segment: str = ""
    evidence: str = ""
    confidence: float | None = None
    rescue_pass: bool = False
    rescue_result: str = ""
    duplicate_chunk_ids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["temporal_context"] = self.temporal_context.to_dict()
        return data
