"""CLI demo for P0.2 spike — runs the fake workflow end-to-end."""

from __future__ import annotations

import json
import sys

from astra_multi.workflow import SAMPLE_INPUT, create_compiled_workflow


def main():
    print("=" * 60)
    print("Astra Multi — P0 Spike: Fake Workflow Demo")
    print("=" * 60)

    workflow = create_compiled_workflow()

    print("\nRunning workflow with sample task...")
    print(f"Task: {SAMPLE_INPUT['task']['goal']}")
    print(f"Max rounds: {SAMPLE_INPUT['max_rounds']}")
    print("-" * 60)

    # Stream events
    final_state = None
    for event in workflow.stream(SAMPLE_INPUT, stream_mode="updates"):
        for node_name, update in event.items():
            if "events" in update:
                for ev in update["events"]:
                    print(f"  {ev}")
            if "phase" in update:
                print(f"  -> Phase: {update['phase']}")
        final_state = event

    print("-" * 60)

    # Get final state
    result = workflow.invoke(SAMPLE_INPUT)
    print(f"\nFinal phase: {result.get('phase')}")
    print(f"Gate passed: {result.get('gate_passed')}")
    print(f"Rounds: {result.get('round')}")
    print(f"Stop reason: {result.get('stop_reason', 'none')}")

    # Show analyses
    analyses = result.get("analyses", [])
    print(f"\nIndependent analyses: {len(analyses)}")
    for a in analyses:
        print(f"  - {a['role']}: {len(a['findings'])} findings, marker='{a.get('marker', '')}'")

    # Show plan summary
    plan = result.get("plan")
    if plan:
        print(f"\nPlan revision {plan['revision']}: {len(plan['steps'])} steps")
        for step in plan["steps"]:
            print(f"  {step['id']}: {step['objective']}")

    # Show issues
    issues = result.get("issues", [])
    print(f"\nIssues: {len(issues)}")
    for issue in issues:
        print(f"  {issue['id']}: [{issue['severity']}] {issue['status']} — {issue['claim'][:50]}")

    print("\n" + "=" * 60)
    print("Spike completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
