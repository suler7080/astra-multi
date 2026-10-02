"""Subprocess harness; parents kill a worker at a known durability boundary."""

import json
import sqlite3
import sys
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from astra_multi.domain.models import CheckpointRef, Lease
from astra_multi.domain.policies import LeaseLost
from astra_multi.persistence import CheckpointBridge, SQLiteStore
from astra_multi.persistence.sqlite import mutation_adapter


class GraphState(TypedDict):
    checkpoint: str


def pause(message):
    print(message, flush=True)
    sys.stdin.readline()


def main():
    workspace = Path(sys.argv[1])
    mode = sys.argv[2]
    owner = sys.argv[3] if len(sys.argv) > 3 else "worker"

    def fault(point):
        if mode == point:
            pause("uncommitted")

    with SQLiteStore(workspace / "domain.sqlite", fault=fault) as store:
        if mode == "contend":
            pause("ready")
            try:
                lease = store.acquire("RUN-001", owner)
                print(json.dumps({"winner": owner, "epoch": lease.epoch}), flush=True)
            except LeaseLost:
                print(json.dumps({"lost": owner}), flush=True)
            return
        lease = Lease.model_validate_json((workspace / "lease.json").read_text())
        command = mutation_adapter.validate_json(
            (workspace / "command.json").read_text()
        )
        bridge = CheckpointBridge(store)

        def node(state):
            operation, checkpoint = bridge.commit(
                CheckpointRef.model_validate_json(state["checkpoint"]), command, lease
            )
            if mode == "after_domain_commit":
                pause("committed")
            return {"checkpoint": checkpoint.model_dump_json()}

        graph = StateGraph(GraphState)
        graph.add_node("commit_candidate", node)
        graph.set_entry_point("commit_candidate")
        graph.add_edge("commit_candidate", END)
        with sqlite3.connect(
            workspace / "checkpoint.sqlite", check_same_thread=False
        ) as connection:
            workflow = graph.compile(checkpointer=SqliteSaver(connection))
            config = {"configurable": {"thread_id": "RUN-001"}}
            if mode == "restart":
                result = workflow.invoke(None, config)
            else:
                result = workflow.invoke(
                    {"checkpoint": bridge.reference("RUN-001").model_dump_json()},
                    config,
                )
            print(result["checkpoint"], flush=True)


if __name__ == "__main__":
    main()
