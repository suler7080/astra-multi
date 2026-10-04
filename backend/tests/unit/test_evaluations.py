"""Unit tests for P6.2 and P6.3 evaluation benchmark harness and scoring rubric."""

import sys
from pathlib import Path

# Ensure repository root is on sys.path to import evaluations
repo_root = Path(__file__).resolve().parent.parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from evaluations.baseline_runner import BaselineRunner  # noqa: E402
from evaluations.multi_agent_runner import MultiAgentRunner  # noqa: E402
from evaluations.report_generator import BenchmarkReportGenerator  # noqa: E402
from evaluations.scoring import EvaluationScorer  # noqa: E402


def test_baseline_and_multi_agent_runners_produce_valid_plans():
    task = {
        "id": "TASK-TEST-01",
        "category": "bug_fix",
        "title": "Fix concurrency race condition",
        "goal": "Ensure mutex locking around state mutation",
        "requirements": ["Add Lock", "Test concurrent writers"],
        "constraints": ["No external packages"],
        "acceptance_criteria": ["20 threads pass without corruption"],
    }

    base_runner = BaselineRunner()
    base_res = base_runner.run_task(task)
    assert base_res["system"] == "single_model_baseline"
    assert "plan" in base_res
    assert len(base_res["plan"]["steps"]) == 2

    multi_runner = MultiAgentRunner()
    multi_res = multi_runner.run_task(task)
    assert multi_res["system"] == "astra_multi_agent"
    assert "plan" in multi_res
    assert multi_res["quality_gate_passed"] is True
    # Multi-agent has extra verification and resilience steps
    assert len(multi_res["plan"]["steps"]) >= 3
    assert len(multi_res["issues"]) >= 1


def test_scoring_rubric_evaluates_blind_and_anonymized():
    task = {
        "id": "TASK-TEST-02",
        "category": "migration",
        "title": "Migrate database schema",
        "goal": "Zero downtime schema evolution",
        "requirements": ["Create migration script", "Add downgrade"],
        "constraints": ["Zero downtime"],
        "acceptance_criteria": ["Upgrade and downgrade pass"],
    }

    base_res = BaselineRunner().run_task(task)
    multi_res = MultiAgentRunner().run_task(task)

    scorer = EvaluationScorer()
    score_base = scorer.score_plan(base_res, task, anonymized_label="Plan A")
    score_multi = scorer.score_plan(multi_res, task, anonymized_label="Plan B")

    assert score_base.system_label == "Plan A"
    assert score_multi.system_label == "Plan B"
    assert 0.0 <= score_base.mean_score <= 4.0
    assert 0.0 <= score_multi.mean_score <= 4.0
    # Multi-agent addresses omissions that baseline misses in migration tasks
    assert score_multi.critical_omissions == 0
    assert score_multi.mean_score > score_base.mean_score


def test_benchmark_report_generator_audit_thresholds():
    manifest_path = repo_root / "evaluations" / "dataset_manifest.json"
    generator = BenchmarkReportGenerator(dataset_path=manifest_path)
    stats = generator.run_benchmark()

    assert stats["sample_count"] == 12
    assert stats["pilot_status"] == "PILOT_PASSED"
    assert stats["gates_audit"]["quality_ge_baseline"] is True
    assert stats["gates_audit"]["omissions_le_baseline"] is True
    assert stats["gates_audit"]["measured_improvement"] is True
    assert stats["gates_audit"]["reliability_invariants_pass"] is True
    assert stats["gates_audit"]["budget_cap_respected"] is True

    # Delta checks
    assert stats["comparison"]["quality_delta"] > 0
    assert stats["comparison"]["omissions_reduced"] > 0
    assert stats["multi_agent"]["re_plan_rate"] == 0.0
