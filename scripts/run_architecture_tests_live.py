"""Execution script for architecture design tests 1, 2, and 3 using live Astra Multi workflow engine."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("eval_runner")

# Add backend/src to sys.path
backend_src = Path(__file__).resolve().parent.parent / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

from astra_multi.api.routes_auth_settings import apply_all_providers_to_environment
from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.models import (
    Requirement,
    Run,
    RunPhase,
    RunStatus,
    TaskSpec,
)
from astra_multi.exports.exporter import PlanExporter
from astra_multi.exports.finalization import FinalizationService
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore


def build_test1_spec() -> TaskSpec:
    base_requirements = [
        Requirement(
            id="REQ-001",
            text="Hệ thống front-end thuần cho chợ freelancer chạy hoàn toàn trên static hosting",
            acceptance="Chỉ sử dụng HTML, CSS, Vanilla JS, jQuery, Bootstrap 5. Không dùng bất kỳ framework SPA nào (React, Vue, Angular) hay backend riêng. Tương thích static hosting.",
        ),
        Requirement(
            id="REQ-002",
            text="Giao tiếp dữ liệu qua MockAPI",
            acceptance="Toàn bộ dữ liệu được lấy từ MockAPI qua lớp API tập trung, không phân tán lệnh AJAX/fetch trong các trang.",
        ),
        Requirement(
            id="REQ-003",
            text="Cơ chế làm việc song song cho 4 lập trình viên",
            acceptance="Cấu trúc mã nguồn và phân công module rõ ràng, không để hai lập trình viên sửa cùng một file nhằm tránh xung đột mã.",
        ),
    ]

    expected_outputs = [
        "Sơ đồ cấu trúc thư mục (pages, components/partials, js/api, js/utils, css)",
        "Quy ước tách lớp: gọi API / xử lý dữ liệu / render DOM",
        "Cách dùng lại header/footer giữa các trang không cần framework",
        "Cơ chế quản lý trạng thái đăng nhập (localStorage/sessionStorage)",
        "Bảng phân công module cho 4 thành viên",
    ]

    reqs = list(base_requirements)
    for idx, eo in enumerate(expected_outputs, start=len(base_requirements) + 1):
        reqs.append(
            Requirement(
                id=f"REQ-{idx:03d}",
                text=eo,
                acceptance=f"Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: {eo}",
            )
        )

    return TaskSpec(
        id="TASK-TEST1",
        goal="Thiết kế kiến trúc front-end cho website chợ freelancer (đăng việc, tìm việc, xem hồ sơ, nhắn tin cơ bản) đáp ứng hoàn toàn ràng buộc thuần front-end và tĩnh.",
        requirements=reqs,
        constraints=[
            "Chỉ dùng HTML, CSS, Vanilla JS, jQuery, Bootstrap 5.",
            "Dữ liệu lấy từ MockAPI; không có backend riêng.",
            "Không dùng React, Vue, Angular hay bất kỳ framework SPA nào.",
            "Nhóm 4 người làm song song, ít xung đột file.",
            "Chạy được khi mở bằng static hosting.",
        ],
        non_goals=[
            "Không xây dựng backend server riêng (NodeJS, Python, PHP, v.v.).",
            "Không dùng cơ sở dữ liệu riêng (MySQL, PostgreSQL, MongoDB, v.v.).",
            "Không cài đặt các build tool phức tạp hay SPA routing framework.",
        ],
    )


def build_test2_spec() -> TaskSpec:
    base_requirements = [
        Requirement(
            id="REQ-001",
            text="Cơ chế thống nhất xử lý loading, lỗi mạng, dữ liệu rỗng và hết hạn phiên cho toàn bộ ứng dụng",
            acceptance="Có một điểm vào duy nhất (single entry point / API client wrapper) cho mọi request để quản lý vòng đời và trạng thái.",
        ),
        Requirement(
            id="REQ-002",
            text="Xử lý giới hạn tốc độ và lỗi MockAPI (429/500)",
            acceptance="Phân biệt lỗi có thể thử lại (retryable) và lỗi không thể thử lại (non-retryable), áp dụng chiến lược retry có kiểm soát (số lần, khoảng chờ).",
        ),
        Requirement(
            id="REQ-003",
            text="Giao diện phản hồi trạng thái bằng Bootstrap 5",
            acceptance="Thông báo lỗi hiển thị bằng Bootstrap 5 (toast/alert), có xử lý trạng thái rỗng (empty state) và không chặn giao diện vô thời hạn.",
        ),
    ]

    expected_outputs = [
        "Sơ đồ luồng một request: gửi → loading → thành công/lỗi → render",
        "Danh sách mã lỗi và cách phản hồi tương ứng trên UI",
        "Chiến lược retry (số lần, thời gian chờ) và khi nào không retry",
        "Mẫu mã giả cho hàm bọc request dùng chung",
    ]

    reqs = list(base_requirements)
    for idx, eo in enumerate(expected_outputs, start=len(base_requirements) + 1):
        reqs.append(
            Requirement(
                id=f"REQ-{idx:03d}",
                text=eo,
                acceptance=f"Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: {eo}",
            )
        )

    return TaskSpec(
        id="TASK-TEST2",
        goal="Thiết kế cơ chế thống nhất xử lý loading, lỗi mạng, dữ liệu rỗng và hết hạn phiên cho MockAPI trong ứng dụng chợ freelancer.",
        requirements=reqs,
        constraints=[
            "MockAPI giới hạn tốc độ và đôi khi trả 429/500.",
            "Chỉ dùng jQuery AJAX hoặc fetch, không thêm thư viện ngoài (như Axios, TanStack Query, v.v.).",
            "Thông báo lỗi hiển thị bằng Bootstrap 5 (toast/alert).",
        ],
        non_goals=[
            "Không sử dụng các thư viện quản lý state bên ngoài hay hệ thống backend telemetry.",
            "Không thêm runtime dependencies ngoài jQuery, Bootstrap 5 và Vanilla JS.",
        ],
    )


def build_test3_spec() -> TaskSpec:
    base_requirements = [
        Requirement(
            id="REQ-001",
            text="Cơ chế phân quyền cho 3 vai trò: khách, freelancer, nhà tuyển dụng",
            acceptance="Ma trận phân quyền đầy đủ: Vai trò × Trang × Hành động.",
        ),
        Requirement(
            id="REQ-002",
            text="Cơ chế bảo vệ trang và điều hướng trước khi render (Early Guard)",
            acceptance="Guard chạy trước khi render DOM nội dung trang để tránh nháy nội dung cấm (flicker). Không dùng thư viện router ngoài.",
        ),
        Requirement(
            id="REQ-003",
            text="Minh bạch về giới hạn và rủi ro bảo mật client-side",
            acceptance="Nêu rõ kiểm soát client-side chỉ là trải nghiệm giao diện người dùng, không phải bảo mật thực sự vì người dùng có thể can thiệp devtools/localStorage. Không gợi ý backend nằm ngoài ràng buộc.",
        ),
    ]

    expected_outputs = [
        "Ma trận vai trò × trang × hành động",
        "Cơ chế chặn truy cập trang (guard) chạy trước khi render",
        "Cách ẩn/hiện thành phần UI theo vai trò",
        "Phần 'Giới hạn và rủi ro' nói thẳng rằng kiểm soát phía client chỉ là trải nghiệm, không phải bảo mật thật",
    ]

    reqs = list(base_requirements)
    for idx, eo in enumerate(expected_outputs, start=len(base_requirements) + 1):
        reqs.append(
            Requirement(
                id=f"REQ-{idx:03d}",
                text=eo,
                acceptance=f"Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: {eo}",
            )
        )

    return TaskSpec(
        id="TASK-TEST3",
        goal="Thiết kế cơ chế phân quyền cho 3 vai trò (khách, freelancer, nhà tuyển dụng) và bảo vệ trang client-side cho website chợ freelancer.",
        requirements=reqs,
        constraints=[
            "Không có backend; quyền được lưu trong dữ liệu MockAPI.",
            "Phải nêu rõ giới hạn bảo mật của phía client.",
            "Không dùng thư viện router (như React Router, Page.js, Navigo).",
        ],
        non_goals=[
            "Không thêm backend authentication server (như OAuth2/JWT signing server).",
            "Không dùng thư viện router ngoài.",
        ],
    )


def prepare_eval_store(db_path: Path, artifacts_dir: Path, source_db: Path) -> SQLiteStore:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Initialize target SQLite schema
    store = SQLiteStore(db_path, FileArtifactStore(artifacts_dir))

    # Copy settings and provider_configs from source_db if they exist
    if source_db.exists():
        src_conn = sqlite3.connect(source_db)
        dst_conn = sqlite3.connect(db_path)
        try:
            for tbl in ["app_settings", "provider_configs"]:
                try:
                    src_cur = src_conn.cursor()
                    src_cur.execute(f"SELECT * FROM {tbl}")
                    rows = src_cur.fetchall()
                    if rows:
                        col_count = len(rows[0])
                        placeholders = ",".join("?" * col_count)
                        dst_conn.executemany(f"INSERT OR REPLACE INTO {tbl} VALUES ({placeholders})", rows)
                        dst_conn.commit()
                        logger.info("Copied %d rows from %s.%s to eval db", len(rows), source_db.name, tbl)
                except Exception as e:
                    logger.warning("Could not copy table %s: %s", tbl, e)
        finally:
            src_conn.close()
            dst_conn.close()

    # Synchronize providers into env
    apply_all_providers_to_environment(store)
    return store


def execute_test(test_num: int, task: TaskSpec, store: SQLiteStore, out_dir: Path) -> dict:
    run_id = f"RUN-ARCH-TEST{test_num}-{int(time.time())}"
    logger.info("==================================================")
    logger.info("STARTING TEST %d: %s (Run ID: %s)", test_num, task.goal[:60], run_id)
    logger.info("Requirements: %d items, Constraints: %d items", len(task.requirements), len(task.constraints))
    logger.info("==================================================")

    # Create run in store
    run = Run(
        id=run_id,
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="design",
        config_hash="0" * 64,
    )
    store.create(task, run, snapshot=None)

    lease = store.acquire(run_id, owner=f"eval-worker-{test_num}", ttl=600)
    controller = WorkflowController(store, lease, actor="eval-worker")
    context_builder = ContextBuilder(store.artifacts)

    # Model gateway with auto repair
    gateway = ModelGateway(config=GatewayConfig(enable_output_repair=True, default_max_retries=2))

    active_p = store.settings.get_active_provider()
    active_provider_name = active_p["name"] if active_p else "xkiro"

    wf_ctx = WorkflowContext(
        controller=controller,
        gateway=gateway,
        context_builder=context_builder,
        budget_service=None,
        provider=active_provider_name,
        role_assignments={},
    )

    graph = create_workflow_graph(wf_ctx)
    app = graph.compile()

    initial_state = {
        "run_id": run_id,
        "round": 0,
        "max_rounds": 1,
        "events": [],
    }

    start_t = time.perf_counter()
    logger.info("Invoking workflow graph for Test %d...", test_num)
    final_output = app.invoke(initial_state, config={"recursion_limit": 150})
    duration = time.perf_counter() - start_t
    logger.info("Workflow graph completed in %.2f seconds", duration)

    # Load final state
    final_state = store.load(run_id)
    logger.info("Run status: %s, phase: %s", final_state.run.status.value, final_state.run.phase.value)
    if final_state.plan:
        logger.info(
            "Plan revision: %d, steps: %d, decisions: %d, artifacts: %d, risks: %d",
            final_state.plan.revision,
            len(final_state.plan.steps),
            len(final_state.plan.decisions),
            len(final_state.plan.design_artifacts),
            len(final_state.plan.risks),
        )

    # Export plan artifacts
    exporter = PlanExporter()
    json_export = exporter.export_json(final_state)
    md_export = exporter.export_markdown(final_state)

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"test{test_num}_plan.json"
    md_path = out_dir / f"test{test_num}_plan.md"

    json_path.write_text(json.dumps(json_export, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(md_export, encoding="utf-8")
    logger.info("Saved exported plan to %s and %s", json_path, md_path)

    # Evaluate finalization
    fin_service = FinalizationService()
    decision = fin_service.evaluate(final_state, getattr(final_state, "semantic_review", None))
    logger.info("Finalization decision: target_status=%s, reason=%s", decision.target_status.value, decision.reason)

    store.release(lease)

    return {
        "test_num": test_num,
        "run_id": run_id,
        "duration": duration,
        "status": final_state.run.status.value,
        "json_path": str(json_path),
        "md_path": str(md_path),
        "plan": json_export,
        "md_content": md_export,
    }


def main():
    parser = argparse.ArgumentParser(description="Run architecture design tests")
    parser.add_argument("--test", type=int, choices=[1, 2, 3], default=None, help="Specific test to run (1, 2, or 3)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    eval_db = repo_root / "backend" / ".local" / "eval_arch.sqlite"
    eval_artifacts = repo_root / "backend" / ".local" / "eval_arch_artifacts"
    source_db = repo_root / "backend" / ".local" / "domain.sqlite"
    output_dir = repo_root / "evaluations" / "results"

    logger.info("Initializing eval store at %s", eval_db)
    store = prepare_eval_store(eval_db, eval_artifacts, source_db)

    tests_to_run = [args.test] if args.test is not None else [1, 2, 3]
    results = {}

    for t_num in tests_to_run:
        if t_num == 1:
            task = build_test1_spec()
        elif t_num == 2:
            task = build_test2_spec()
        elif t_num == 3:
            task = build_test3_spec()
        else:
            continue

        res = execute_test(t_num, task, store, output_dir / f"test{t_num}")
        results[t_num] = res

    logger.info("All requested tests completed successfully!")


if __name__ == "__main__":
    main()
