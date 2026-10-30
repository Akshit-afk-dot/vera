"""Contract v0: the single source of truth shared by agent/, server/ and web/.

Pydantic models here are exported to contracts/schemas/*.json by scripts/export_contracts.py (CI fails
if the exported files are stale). web/ generates TypeScript types from those schemas.
Breaking changes after the v0 freeze need a version bump of CONTRACT_VERSION and a DECISIONS.md line.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = 0


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- domain enums

FaultType = Literal["LOW_CAPACITY", "HIGH_IR", "CURVE_SHAPE", "CAPACITY_CREEP_UP", "NOISY_OR_DEAD_CHANNEL", "LOW_CE"]
Grade = Literal["A", "B", "C", "REJECT"]
Severity = Literal["low", "medium", "high"]
DataLabel = Literal["REAL", "REAL+PLANTED", "SYNTHETIC"]
Role = Literal["planner", "worker"]
RunnerKind = Literal["contree", "tools", "local"]
ColumnRole = Literal[
    "channel_id", "cycle", "step", "time_s", "voltage_v", "current_a", "capacity_ah", "temperature_c", "ignore"
]


# ---------------------------------------------------------------- ingestion

class ColumnMap(Strict):
    source: str = Field(description="Column header as it appears in the file, or 0-based index as a string")
    role: ColumnRole
    unit: str = Field(description="Unit in the file, e.g. 'mV', 'A', 'mAh', 'hh:mm:ss', 's'")
    scale: float = Field(1.0, description="Multiply file values by this to reach the canonical unit")


class LayoutMapping(Strict):
    """Declarative description of a tester export (tier-1 ingestion). Applied by a generic reader."""

    format: Literal["csv", "excel", "mat", "hdf5"]
    encoding: str = "utf-8"
    delimiter: str | None = None
    decimal: Literal[".", ","] = "."
    header_row: int | None = Field(None, description="0-based line (csv) or row (excel) holding column names")
    sheet_pattern: str | None = Field(None, description="Regex of sheet names to read (excel)")
    struct_path: str | None = Field(None, description="Dotted path to the data struct (mat/hdf5)")
    orientation: Literal["long", "wide"] = "long"
    channel_source: Literal["column", "sheet", "file", "wide_column_prefix"] = "column"
    wide_column_prefix: str | None = None
    time_format: Literal["seconds", "minutes", "hours", "hh:mm:ss", "timestamp"] = "seconds"
    current_sign: Literal["charge_positive", "discharge_positive"] = "charge_positive"
    columns: list[ColumnMap]
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


class ValidationCheck(Strict):
    name: str
    ok: bool
    detail: str = ""


class CanonicalRow(Strict):
    """One row of the canonical parquet table both ingestion tiers produce."""

    channel_id: str
    cycle: int
    step: int
    time_s: float
    voltage_v: float
    current_a: float = Field(description="Positive = charge")
    capacity_ah: float | None = None
    temperature_c: float | None = None


# ---------------------------------------------------------------- results

class GradeThresholds(Strict):
    """Capacity bins are % of the reference capacity; IR bins are % of the batch-median IR."""

    basis: Literal["batch_median", "nominal"] = "batch_median"
    nominal_capacity_ah: float | None = None
    capacity_min_pct: dict[Literal["A", "B", "C"], float] = {"A": 98.0, "B": 95.0, "C": 90.0}
    ir_max_pct: dict[Literal["A", "B", "C"], float] = {"A": 115.0, "B": 130.0, "C": 160.0}
    reject_on_flags: list[FaultType] = ["NOISY_OR_DEAD_CHANNEL"]
    max_grade_by_severity: dict[Severity, Grade] = Field(
        default={"high": "C", "medium": "B"}, description="A flagged cell can grade no better than this")
    source: Literal["default", "agent", "user"] = "default"
    rationale: str = ""


class Evidence(Strict):
    metric: str
    value: float
    unit: str
    batch_median: float
    robust_z: float | None = Field(description="None when an absolute sanity limit fired, not a batch statistic")
    threshold: str = Field(description="Human-readable rule that fired, e.g. 'robust_z < -3.5'")
    cycle: int | None = None


class Flag(Strict):
    type: FaultType
    severity: Severity
    evidence: list[Evidence] = Field(min_length=1)
    explanation: str | None = None


class CycleFeatures(Strict):
    cycle: int
    discharge_capacity_ah: float | None = None
    charge_capacity_ah: float | None = None
    ce: float | None = None
    ir_mohm: float | None = None
    mid_voltage_v: float | None = None
    dqdv_peak_v: float | None = None
    noise_mv: float | None = None


class Provenance(Strict):
    run_id: str
    code_ids: list[str] = Field(description="code.generated ids whose execution produced these numbers")
    code_sha256: str
    artifacts: list[str] = Field(default_factory=list, description="Run-relative artifact paths")


class ChannelResult(Strict):
    channel_id: str
    position: tuple[int, int] | None = Field(None, description="(row, col) on the tester tray, for the heatmap")
    grade: Grade
    capacity_ah: float | None = Field(None, description="Grading-cycle discharge capacity")
    ir_mohm: float | None = None
    cycles: list[CycleFeatures]
    flags: list[Flag]
    explanation: str | None = None
    provenance: Provenance


class BatchSummary(Strict):
    n_channels: int
    n_flagged: int
    grade_counts: dict[Grade, int]
    flag_counts: dict[FaultType, int]
    reference_capacity_ah: float
    median_ir_mohm: float | None = None


class BatchResults(Strict):
    v: Literal[0] = 0
    run_id: str
    data_label: DataLabel
    source_name: str
    mapping: LayoutMapping | None = None
    thresholds: GradeThresholds
    summary: BatchSummary
    channels: list[ChannelResult]


# ---------------------------------------------------------------- events (SSE, one JSON object per event)

class EventBase(Strict):
    v: Literal[0] = 0
    run_id: str
    seq: int = Field(ge=0, description="Strictly increasing within a run")
    ts: datetime


class SourceInfo(Strict):
    kind: Literal["upload", "sample"]
    name: str
    size_bytes: int
    sha256: str
    data_label: DataLabel


class RunStarted(EventBase):
    type: Literal["run.started"] = "run.started"
    source: SourceInfo
    mode: Literal["live", "replay"]
    runner: RunnerKind
    models: dict[Role, str]
    provider: str | None = Field(None, description="Model provider, e.g. 'nvidia' (API Catalog) or 'nebius' (Token Factory)")


class MemoryHit(EventBase):
    type: Literal["memory.hit"] = "memory.hit"
    kind: Literal["mapping", "normalizer", "thresholds"]
    fingerprint: str
    saved_at: datetime


class SchemaProposed(EventBase):
    type: Literal["schema.proposed"] = "schema.proposed"
    tier: Literal["declarative", "normalizer"]
    attempt: int
    mapping: LayoutMapping | None = None
    code_id: str | None = Field(None, description="Set for tier=normalizer")


class SchemaValidated(EventBase):
    type: Literal["schema.validated"] = "schema.validated"
    ok: bool
    checks: list[ValidationCheck]
    n_channels: int | None = None
    n_cycles: int | None = None
    n_rows: int | None = None


class SchemaNeedsConfirmation(EventBase):
    type: Literal["schema.needs_confirmation"] = "schema.needs_confirmation"
    reason: str


class LlmCall(EventBase):
    type: Literal["llm.call"] = "llm.call"
    role: Role
    model: str
    purpose: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    cached: bool = False


class CodeGenerated(EventBase):
    type: Literal["code.generated"] = "code.generated"
    code_id: str
    purpose: str
    attempt: int
    sha256: str
    code: str


class SandboxStarted(EventBase):
    type: Literal["sandbox.started"] = "sandbox.started"
    runner: RunnerKind
    code_id: str
    shard: int
    n_shards: int
    channels: list[str]
    operation_id: str | None = None


class SandboxFinished(EventBase):
    type: Literal["sandbox.finished"] = "sandbox.finished"
    code_id: str
    shard: int
    ok: bool
    exit_code: int | None
    duration_s: float
    stdout_tail: str = ""
    stderr_tail: str = ""
    artifacts: list[str] = []
    operation_id: str | None = None


class RepairAttempt(EventBase):
    type: Literal["repair.attempt"] = "repair.attempt"
    attempt: int
    max_attempts: int
    failed_code_id: str
    error_summary: str


class AnalysisProgress(EventBase):
    type: Literal["analysis.progress"] = "analysis.progress"
    done: int
    total: int
    unit: Literal["shards", "channels"]


class ThresholdsProposed(EventBase):
    type: Literal["thresholds.proposed"] = "thresholds.proposed"
    thresholds: GradeThresholds


class ResultsReady(EventBase):
    type: Literal["results.ready"] = "results.ready"
    summary: BatchSummary


class VerifyClaimFailed(EventBase):
    type: Literal["verify.claim_failed"] = "verify.claim_failed"
    sentence: str
    claim: str
    reason: str
    action: Literal["regenerated", "dropped"]


class VerifySummary(EventBase):
    type: Literal["verify.summary"] = "verify.summary"
    claims_checked: int
    claims_failed: int
    sentences_regenerated: int
    sentences_dropped: int


class ReportReady(EventBase):
    type: Literal["report.ready"] = "report.ready"
    formats: list[Literal["md", "pdf"]]


class RunFailed(EventBase):
    type: Literal["run.failed"] = "run.failed"
    stage: str
    error: str


class RunFinished(EventBase):
    type: Literal["run.finished"] = "run.finished"
    duration_s: float
    tokens_in: int
    tokens_out: int
    cost_usd: float


Event = Annotated[
    RunStarted | MemoryHit | SchemaProposed | SchemaValidated | SchemaNeedsConfirmation | LlmCall | CodeGenerated
    | SandboxStarted | SandboxFinished | RepairAttempt | AnalysisProgress | ThresholdsProposed | ResultsReady
    | VerifyClaimFailed | VerifySummary | ReportReady | RunFailed | RunFinished,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------- HTTP API bodies

class SampleInfo(Strict):
    id: str
    name: str
    description: str
    data_label: DataLabel
    n_channels: int
    size_bytes: int
    has_replay: bool


class RunCreated(Strict):
    run_id: str
    events_url: str
    mode: Literal["live", "replay"]


class RegradeRequest(Strict):
    thresholds: GradeThresholds


class ApiError(Strict):
    error: str
    detail: str = ""
