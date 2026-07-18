"""
Results report: each golden-document test appends one record here (via the
`eval_results` fixture in conftest.py); at session end the records are
written to tests/evals/.results/latest.json. ci/check_thresholds.py reads
that file to decide pass/fail — decoupled from pytest's own exit code so the
"no backend yet -> skip cleanly" state and the "backend exists -> gate for
real" state are both handled explicitly rather than by accident.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

RESULTS_DIR = Path(__file__).resolve().parent.parent / ".results"
LATEST_PATH = RESULTS_DIR / "latest.json"
BASELINE_PATH = RESULTS_DIR / "baseline.json"


@dataclass
class FixtureResult:
    fixture_id: str
    category: str
    trajectory_passed: Optional[bool]  # None = skipped (no backend yet)
    trajectory_failure: Optional[str] = None
    field_accuracy: Optional[float] = None
    is_adversarial: bool = False
    is_faithfulness_violation_case: bool = False
    skipped_reason: Optional[str] = None


@dataclass
class EvalRunReport:
    mode: str  # "mock" | "real"
    results: list[FixtureResult] = field(default_factory=list)

    def add(self, result: FixtureResult) -> None:
        self.results.append(result)

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "results": [asdict(r) for r in self.results]}

    def write(self, path: Path = LATEST_PATH) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str))

    @classmethod
    def load(cls, path: Path = LATEST_PATH) -> Optional["EvalRunReport"]:
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls(mode=data["mode"], results=[FixtureResult(**r) for r in data["results"]])
