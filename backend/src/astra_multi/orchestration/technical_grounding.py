"""Technical Grounding Engine for Greenfield Architecture Planning.

Establishes physical reality boundaries during INVESTIGATE and enforces them at VERIFY:
1. file:// protocol: Origin is null; browser blocks local fetch() and <script type="module"> via CORS.
   Mandate: Reusable layout via <script defer src="layout.js"> (template literals/innerHTML).
2. MockAPI.io: Pure static REST CRUD; no server-side JWT generation, token verification, or bcrypt.
   Mandate: Client-driven auth via GET /users?username=... and sessionStorage/localStorage.
3. UX Real-time/Chat: No full page reload or redirects after sending a message.
   Mandate: Direct asynchronous DOM update + controlled interval polling.
4. No framework / No build step: No bundler (Vite/Webpack) or build/dist directories.
   Mandate: Direct source execution with relative paths (./).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from astra_multi.domain.models import (
    Issue,
    IssueSeverity,
    IssueStatus,
    TaskSpec,
    TechStackTruthEntry,
    TechStackTruthTable,
)


@dataclass(frozen=True)
class GroundingViolation:
    tech_id: str
    technology: str
    claim: str
    impact: str
    suggested_resolution: str
    severity: IssueSeverity
    related_req_ids: list[str]
    prohibited_pattern_matched: str


def extract_task_full_text(task: TaskSpec) -> str:
    """Concatenate all task requirements, goals, constraints, and criteria for keyword inspection."""
    texts = [task.goal]
    for r in task.requirements:
        texts.append(r.text)
        texts.extend(r.acceptance_criteria)
        if getattr(r, "verifiable_deliverable", None):
            texts.append(r.verifiable_deliverable or "")
    texts.extend(task.constraints)
    texts.extend(task.acceptance_criteria)
    return " ".join(texts).lower()


def build_tech_stack_truth_table(task: TaskSpec) -> TechStackTruthTable:
    """Builds a TechStackTruthTable recording physical boundaries for technologies specified in task."""
    full_text = extract_task_full_text(task)
    entries: list[TechStackTruthEntry] = []

    # 1. file:// Protocol Grounding
    file_keywords = (
        "file://",
        "file:",
        "mở trực tiếp",
        "mo truc tiep",
        "mở thẳng",
        "mo thang",
        "double-click",
        "không cần web server",
        "khong can web server",
        "no web server",
        "static local",
    )
    if any(kw in full_text for kw in file_keywords) or ("index.html" in full_text and ("trực tiếp" in full_text or "local" in full_text or "static" in full_text)):
        related_ids = [
            r.id for r in task.requirements
            if any(k in (r.text + " " + " ".join(r.acceptance_criteria)).lower() for k in ("file", "layout", "header", "footer", "mở trực tiếp", "html", "tái sử dụng"))
        ]
        entries.append(
            TechStackTruthEntry(
                tech_id="TECH-FILE-PROTOCOL",
                technology="file:// Protocol",
                physical_limitation=(
                    "Trình duyệt đặt Origin: null khi mở file trực tiếp qua giao thức file://. "
                    "Chính sách CORS chặn hoàn toàn fetch() nội bộ tới file .html/.json cục bộ "
                    "và chặn thẻ <script type=\"module\"> hoặc cú pháp import ES Module."
                ),
                mandated_pattern=(
                    "Tái sử dụng Header/Footer hoặc layout chung bắt buộc phải dùng thẻ <script defer src=\"layout.js\"></script> "
                    "kết hợp tiêm DOM trực tiếp bằng template literal / innerHTML / hàm render; "
                    "dùng script thông thường với global namespace (window.AstraApp), tuyệt đối không dùng fetch('header.html') hay ES module import."
                ),
                prohibited_patterns=[
                    "fetch('header.html')",
                    "fetch(\"header.html\")",
                    "fetch('footer.html')",
                    "fetch(\"footer.html\")",
                    "fetch('partials/",
                    "fetch(\"partials/",
                    "type=\"module\"",
                    "type='module'",
                    "import ... from",
                    "es module",
                    "nạp partial bằng fetch",
                    "load header bằng fetch",
                ],
                related_req_ids=related_ids,
            )
        )

    # 2. MockAPI.io Grounding
    mockapi_keywords = ("mockapi", "mockapi.io", "mock api", "mock-api")
    if any(kw in full_text for kw in mockapi_keywords):
        related_ids = [
            r.id for r in task.requirements
            if any(k in (r.text + " " + " ".join(r.acceptance_criteria)).lower() for k in ("mockapi", "mock api", "api", "auth", "login", "đăng nhập", "user"))
        ]
        entries.append(
            TechStackTruthEntry(
                tech_id="TECH-MOCKAPI",
                technology="MockAPI.io REST Backend",
                physical_limitation=(
                    "MockAPI.io chỉ là dịch vụ lưu trữ JSON tĩnh với các endpoint RESTful CRUD cơ bản. "
                    "MockAPI hoàn toàn không có khả năng sinh JWT token có chữ ký số (sign), không kiểm tra "
                    "hạn sử dụng token (expiration) ở phía server, và không hỗ trợ hash/so khớp mật khẩu (bcrypt) ở tầng backend."
                ),
                mandated_pattern=(
                    "Luồng xác thực đăng nhập phải thiết kế truy vấn danh sách GET /users?username=... (hoặc GET /users) "
                    "và tự quản lý trạng thái phiên, so khớp thông tin hoàn toàn ở phía client (sessionStorage/localStorage). "
                    "Không được giả định MockAPI sinh JWT hoặc bảo mật tầng server."
                ),
                prohibited_patterns=[
                    "jwt.sign",
                    "mockapi sinh jwt",
                    "sinh jwt từ mockapi",
                    "server-side jwt",
                    "jwt token từ mockapi",
                    "mockapi trả về jwt",
                    "kiểm tra hết hạn token ở server mockapi",
                    "mockapi hash mật khẩu",
                    "mockapi bcrypt",
                ],
                related_req_ids=related_ids,
            )
        )

    # 3. UX Real-time / Chat Grounding
    chat_keywords = ("chat", "tin nhắn", "tin nhan", "nhắn tin", "nhan tin", "messaging", "message", "real-time", "realtime")
    if any(kw in full_text for kw in chat_keywords):
        related_ids = [
            r.id for r in task.requirements
            if any(k in (r.text + " " + " ".join(r.acceptance_criteria)).lower() for k in ("chat", "tin nhắn", "nhắn tin", "message", "messaging", "real-time", "realtime"))
        ]
        entries.append(
            TechStackTruthEntry(
                tech_id="TECH-REALTIME-CHAT",
                technology="Real-Time / Chat UX",
                physical_limitation=(
                    "Trong ứng dụng web tĩnh và MockAPI, việc tải lại trang hoặc redirect sau mỗi tin nhắn "
                    "sẽ phá hủy toàn bộ trạng thái DOM cục bộ, gây chớp nháy trắng (flicker) và làm hỏng trải nghiệm người dùng. "
                    "Tải lại trang không giúp tránh được giới hạn rate-limit hay CORS."
                ),
                mandated_pattern=(
                    "Nghiêm cấm dùng window.location.reload() hoặc redirect trang sau khi gửi tin nhắn; "
                    "phải gửi POST bất đồng bộ qua AJAX/fetch tới MockAPI và cập nhật DOM trực tiếp (appendChild / innerHTML / render) "
                    "sau khi nhận phản hồi thành công, kết hợp cơ chế polling có kiểm soát (setInterval) để nhận tin nhắn mới."
                ),
                prohibited_patterns=[
                    "window.location.reload()",
                    "location.reload()",
                    "location.reload",
                    "tải lại trang sau mỗi tin nhắn",
                    "reload lại trang sau khi gửi tin nhắn",
                    "reload trang sau mỗi tin nhắn",
                    "redirect sau khi gửi tin nhắn",
                    "redirect sau mỗi tin nhắn",
                ],
                related_req_ids=related_ids,
            )
        )

    # 4. No Framework / No Build Step Grounding
    no_build_keywords = (
        "không dùng framework",
        "khong dung framework",
        "no framework",
        "không framework",
        "không dùng bundler",
        "no bundler",
        "no build",
        "không có bước build",
        "khong co buoc build",
        "không có build",
        "khong co build",
        "không build",
        "khong build",
        "no-build",
        "static hosting",
    )
    if any(kw in full_text for kw in no_build_keywords):
        related_ids = [
            r.id for r in task.requirements
            if any(k in (r.text + " " + " ".join(r.acceptance_criteria)).lower() for k in ("framework", "build", "bundler", "static", "hosting", "deploy"))
        ]
        entries.append(
            TechStackTruthEntry(
                tech_id="TECH-NO-BUILD",
                technology="No-Build / Static Hosting",
                physical_limitation=(
                    "Dự án tuân thủ ràng buộc web tĩnh không qua biên dịch: không dùng bundler (Webpack, Vite, Rollup) "
                    "và không có bước build (build step). Tất cả file HTML, CSS, JS phải chạy trực tiếp từ mã nguồn."
                ),
                mandated_pattern=(
                    "Tất cả đường dẫn tài nguyên phải là đường dẫn tương đối (./, ../). "
                    "Không tạo hoặc tham chiếu đến thư mục build/ hoặc dist/ trong cấu trúc thư mục hoặc kế hoạch triển khai."
                ),
                prohibited_patterns=[
                    "build/",
                    "dist/",
                    "thư mục build",
                    "thu muc build",
                    "thư mục dist",
                    "thu muc dist",
                    "npm run build",
                    "vite build",
                    "webpack build",
                ],
                related_req_ids=related_ids,
            )
        )

    return TechStackTruthTable(entries=entries)


def is_negated_or_prohibition(text: str, match_pos: int, matched_text: str = "") -> bool:
    """Checks whether a matched prohibited pattern is preceded by negation or explicit rejection keywords.

    Prevents false positives on valid instructions like 'KHÔNG dùng window.location.reload()' or
    'không reload trang khi gửi tin nhắn'.
    """
    prefix = text[max(0, match_pos - 70):match_pos].lower()
    negation_signals = (
        "không ",
        "khong ",
        "cấm ",
        "cam ",
        "tránh ",
        "tranh ",
        "do not ",
        "dont ",
        "don't ",
        "never ",
        "avoid ",
        "without ",
        "prohibit",
        "no ",
        "thay vì ",
        "thay vi ",
        "instead of ",
        "nghiêm cấm",
        "tuyệt đối không",
    )
    if any(sig in prefix for sig in negation_signals):
        return True

    if matched_text:
        m_lower = matched_text.lower()
        if any(
            sig in m_lower
            for sig in (
                "không reload",
                "khong reload",
                "không tải lại",
                "khong tai lai",
                "không redirect",
                "khong redirect",
                "no reload",
                "without reload",
                "tránh reload",
                "tranh reload",
                "cấm reload",
            )
        ):
            return True

    return False


def _collect_text_corpus(proposal: Any | None, plan: Any | None) -> list[str]:
    """Flattens all text fields from candidate proposal and plan for scanning."""
    corpus: list[str] = []

    # Proposal content
    if proposal:
        if isinstance(proposal, dict):
            corpus.append(str(proposal.get("approach", "")))
            for alt in proposal.get("alternatives", []):
                corpus.append(str(alt))
            for tr in proposal.get("tradeoffs", []):
                corpus.append(str(tr))
            for req_cov in proposal.get("requirement_coverage", {}).values():
                corpus.append(str(req_cov))
        else:
            corpus.append(getattr(proposal, "approach", ""))
            for alt in getattr(proposal, "alternatives", []):
                corpus.append(str(alt))
            for tr in getattr(proposal, "tradeoffs", []):
                corpus.append(str(tr))
            cov = getattr(proposal, "requirement_coverage", {})
            if isinstance(cov, dict):
                for req_cov in cov.values():
                    corpus.append(str(req_cov))

    # Plan content
    if plan:
        steps = plan.get("steps", []) if isinstance(plan, dict) else getattr(plan, "steps", [])
        for s in steps:
            if isinstance(s, dict):
                corpus.append(str(s.get("objective", "")))
                corpus.append(str(s.get("validation", "")))
                for t in s.get("targets", []):
                    corpus.append(str(t))
                for d in s.get("deliverables", []):
                    corpus.append(str(d))
                for c in s.get("completion_criteria", []):
                    corpus.append(str(c))
                for rf in s.get("requirement_fulfillments", []):
                    if isinstance(rf, dict):
                        corpus.append(str(rf.get("concrete_deliverable", "")))
                        corpus.append(str(rf.get("fulfilled_by_section", "")))
                        corpus.append(str(rf.get("verification_method", "")))
            else:
                corpus.append(getattr(s, "objective", ""))
                corpus.append(getattr(s, "validation", ""))
                for t in getattr(s, "targets", []):
                    corpus.append(str(t))
                for d in getattr(s, "deliverables", []):
                    corpus.append(str(d))
                for c in getattr(s, "completion_criteria", []):
                    corpus.append(str(c))
                for rf in getattr(s, "requirement_fulfillments", []):
                    corpus.append(getattr(rf, "concrete_deliverable", ""))
                    corpus.append(getattr(rf, "fulfilled_by_section", ""))
                    corpus.append(getattr(rf, "verification_method", ""))

        decisions = plan.get("decisions", []) if isinstance(plan, dict) else getattr(plan, "decisions", [])
        for d in decisions:
            if isinstance(d, dict):
                corpus.append(str(d.get("question", "")))
                corpus.append(str(d.get("chosen", "")))
                corpus.append(str(d.get("rationale", "")))
                for alt in d.get("alternatives", []):
                    corpus.append(str(alt))
            else:
                corpus.append(getattr(d, "question", ""))
                corpus.append(getattr(d, "chosen", ""))
                corpus.append(getattr(d, "rationale", ""))
                for alt in getattr(d, "alternatives", []):
                    corpus.append(str(alt))

        artifacts = plan.get("design_artifacts", []) if isinstance(plan, dict) else getattr(plan, "design_artifacts", [])
        for a in artifacts:
            if isinstance(a, dict):
                corpus.append(str(a.get("title", "")))
                corpus.append(str(a.get("content", "")))
            else:
                corpus.append(getattr(a, "title", ""))
                corpus.append(getattr(a, "content", ""))

    return corpus


def verify_technical_grounding(
    task: TaskSpec,
    proposal: Any | None,
    plan: Any | None,
    truth_table: TechStackTruthTable | None = None,
) -> list[GroundingViolation]:
    """Scans proposal and plan against the TechStackTruthTable physical constraints.

    Returns a list of GroundingViolation objects for any prohibited patterns found.
    """
    if truth_table is None:
        truth_table = build_tech_stack_truth_table(task)

    if not truth_table.entries:
        return []

    corpus = _collect_text_corpus(proposal, plan)
    if not corpus:
        return []

    violations: list[GroundingViolation] = []
    seen_violations: set[tuple[str, str]] = set()

    # Pre-compile regex for specialized checks
    regex_fetch_html = re.compile(r"fetch\s*\(\s*['\"][^'\"]*\.html['\"]\s*\)", re.IGNORECASE)
    regex_es_module_script = re.compile(r"<\s*script[^>]*type\s*=\s*['\"]module['\"]", re.IGNORECASE)
    regex_es_import_statement = re.compile(r"\bimport\s+.*?\s+from\s+['\"][./]", re.IGNORECASE)
    regex_build_target = re.compile(r"\b(build|dist)/", re.IGNORECASE)
    regex_reload_on_msg = re.compile(r"(location\.reload|tải lại trang|reload.*trang|redirect.*trang).{0,50}(tin nhắn|message|chat)", re.IGNORECASE)
    regex_msg_then_reload = re.compile(r"(tin nhắn|message|chat).{0,50}(location\.reload|tải lại trang|reload.*trang|redirect)", re.IGNORECASE)

    for entry in truth_table.entries:
        tech_id = entry.tech_id

        for text_chunk in corpus:
            if not text_chunk:
                continue

            # (1) TECH-FILE-PROTOCOL Checks
            if tech_id == "TECH-FILE-PROTOCOL":
                # Check 1a: fetch('...html')
                match_fetch = regex_fetch_html.search(text_chunk)
                if match_fetch and not is_negated_or_prohibition(text_chunk, match_fetch.start()):
                    matched_str = match_fetch.group(0)
                    key = (tech_id, matched_str)
                    if key not in seen_violations:
                        seen_violations.add(key)
                        violations.append(
                            GroundingViolation(
                                tech_id=tech_id,
                                technology=entry.technology,
                                claim=(
                                    f"[TECH-FILE-PROTOCOL] Plan/Proposal proposes '{matched_str}' to load layout/HTML on file://. "
                                    "Browser sets Origin: null on file://, completely blocking local fetch() due to CORS."
                                ),
                                impact="Application will immediately crash or show CORS Origin: null errors when opened directly.",
                                suggested_resolution=(
                                    "Inject Header/Footer via <script defer src='js/layout.js'> using template literals or DOM innerHTML. "
                                    "Do NOT use fetch() on local HTML partials."
                                ),
                                severity=IssueSeverity.BLOCKING,
                                related_req_ids=entry.related_req_ids,
                                prohibited_pattern_matched=matched_str,
                            )
                        )

                # Check 1b: <script type="module">
                match_mod = regex_es_module_script.search(text_chunk)
                if match_mod and not is_negated_or_prohibition(text_chunk, match_mod.start()):
                    matched_str = match_mod.group(0)
                    key = (tech_id, matched_str)
                    if key not in seen_violations:
                        seen_violations.add(key)
                        violations.append(
                            GroundingViolation(
                                tech_id=tech_id,
                                technology=entry.technology,
                                claim=(
                                    f"[TECH-FILE-PROTOCOL] Plan/Proposal proposes '{matched_str}' on file:// protocol. "
                                    "Browsers block ES module scripts on file:// due to CORS Origin: null restrictions."
                                ),
                                impact="Scripts with type='module' will not execute when double-clicked or opened via file://.",
                                suggested_resolution=(
                                    "Use classic script tags (<script defer src='...'>) and standard browser global objects (e.g. window.AstraApp). "
                                    "Do not use type='module'."
                                ),
                                severity=IssueSeverity.BLOCKING,
                                related_req_ids=entry.related_req_ids,
                                prohibited_pattern_matched=matched_str,
                            )
                        )

                # Check 1c: ES import statement on file://
                match_import = regex_es_import_statement.search(text_chunk)
                if match_import and not is_negated_or_prohibition(text_chunk, match_import.start()):
                    matched_str = match_import.group(0)
                    key = (tech_id, matched_str)
                    if key not in seen_violations:
                        seen_violations.add(key)
                        violations.append(
                            GroundingViolation(
                                tech_id=tech_id,
                                technology=entry.technology,
                                claim=(
                                    f"[TECH-FILE-PROTOCOL] Plan/Proposal specifies ES module import syntax '{matched_str}' on file:// without a bundler. "
                                    "ES module imports fail on file://."
                                ),
                                impact="Runtime syntax error or CORS block prevents JS execution.",
                                suggested_resolution="Load scripts in sequence via <script defer src='...'> tags without ES module import statements.",
                                severity=IssueSeverity.BLOCKING,
                                related_req_ids=entry.related_req_ids,
                                prohibited_pattern_matched=matched_str,
                            )
                        )

            # (2) TECH-MOCKAPI Checks
            elif tech_id == "TECH-MOCKAPI":
                for pattern in entry.prohibited_patterns:
                    pos = text_chunk.lower().find(pattern.lower())
                    if pos != -1 and not is_negated_or_prohibition(text_chunk, pos):
                        key = (tech_id, pattern)
                        if key not in seen_violations:
                            seen_violations.add(key)
                            violations.append(
                                GroundingViolation(
                                    tech_id=tech_id,
                                    technology=entry.technology,
                                    claim=(
                                        f"[TECH-MOCKAPI] Plan/Proposal assumes server-side capability '{pattern}' on MockAPI.io. "
                                        "MockAPI is strictly a static RESTful CRUD mock server with no JWT signing or password hashing."
                                    ),
                                    impact="MockAPI cannot generate JWT tokens, verify token expiration, or securely authenticate users.",
                                    suggested_resolution=(
                                        "Design client-side authentication: query GET /users?username=... and manage login session state "
                                        "in client sessionStorage/localStorage."
                                    ),
                                    severity=IssueSeverity.BLOCKING,
                                    related_req_ids=entry.related_req_ids,
                                    prohibited_pattern_matched=pattern,
                                )
                            )

            # (3) TECH-REALTIME-CHAT Checks
            elif tech_id == "TECH-REALTIME-CHAT":
                # Check for explicit reload or reload combined with chat/message
                has_reload_kw = any(kw in text_chunk.lower() for kw in ("location.reload", "tải lại trang", "reload trang", "redirect sau"))
                if has_reload_kw:
                    m_rc1 = regex_reload_on_msg.search(text_chunk)
                    m_rc2 = regex_msg_then_reload.search(text_chunk)
                    matched_obj = m_rc1 or m_rc2
                    if matched_obj and not is_negated_or_prohibition(text_chunk, matched_obj.start(), matched_obj.group(0)):
                        matched_str = matched_obj.group(0)
                        key = (tech_id, matched_str)
                        if key not in seen_violations:
                            seen_violations.add(key)
                            violations.append(
                                GroundingViolation(
                                    tech_id=tech_id,
                                    technology=entry.technology,
                                    claim=(
                                        f"[TECH-REALTIME-CHAT] Plan/Proposal uses page reload or redirect in messaging flow ('{matched_str}'). "
                                        "Reloading destroys ephemeral DOM state and produces severe flicker."
                                    ),
                                    impact="Unacceptable UX and does not bypass CORS or API rate-limits.",
                                    suggested_resolution=(
                                        "Send asynchronous POST (fetch/AJAX) to MockAPI and update the message list DOM directly upon response. "
                                        "Use controlled interval polling to fetch incoming messages."
                                    ),
                                    severity=IssueSeverity.BLOCKING,
                                    related_req_ids=entry.related_req_ids,
                                    prohibited_pattern_matched=matched_str,
                                )
                            )

            # (4) TECH-NO-BUILD Checks
            elif tech_id == "TECH-NO-BUILD":
                # Check target/deliverable references to build/ or dist/
                match_build = regex_build_target.search(text_chunk)
                if match_build and not is_negated_or_prohibition(text_chunk, match_build.start()):
                    matched_str = match_build.group(0)
                    key = (tech_id, matched_str)
                    if key not in seen_violations:
                        seen_violations.add(key)
                        violations.append(
                            GroundingViolation(
                                tech_id=tech_id,
                                technology=entry.technology,
                                claim=(
                                    f"[TECH-NO-BUILD] Plan/Proposal references '{matched_str}' directory under a zero-build / static hosting constraint. "
                                    "No build or compilation step exists."
                                ),
                                impact="Build directory does not exist and relative links pointing into it will 404.",
                                suggested_resolution="Reference and serve all files directly from the source repository using relative paths (./).",
                                severity=IssueSeverity.BLOCKING,
                                related_req_ids=entry.related_req_ids,
                                prohibited_pattern_matched=matched_str,
                            )
                        )

                # Check phrases like "thư mục build"
                for build_phrase in ("thư mục build", "thu muc build", "npm run build"):
                    pos = text_chunk.lower().find(build_phrase)
                    if pos != -1 and not is_negated_or_prohibition(text_chunk, pos):
                        key = (tech_id, build_phrase)
                        if key not in seen_violations:
                            seen_violations.add(key)
                            violations.append(
                                GroundingViolation(
                                    tech_id=tech_id,
                                    technology=entry.technology,
                                    claim=f"[TECH-NO-BUILD] Plan/Proposal refers to '{build_phrase}' but build tools/steps are prohibited.",
                                    impact="Violates static hosting constraints.",
                                    suggested_resolution="Eliminate build step and host raw source files directly.",
                                    severity=IssueSeverity.BLOCKING,
                                    related_req_ids=entry.related_req_ids,
                                    prohibited_pattern_matched=build_phrase,
                                )
                            )

    return violations


def grounding_violations_to_issues(
    violations: list[GroundingViolation],
    run_id: str,
    round_num: int,
    base_revision: int,
    valid_task_requirements: set[str],
) -> list[Issue]:
    """Converts a list of GroundingViolation instances into valid domain Issue entities."""
    issues: list[Issue] = []
    fallback_req = next(iter(valid_task_requirements)) if valid_task_requirements else "REQ-001"

    for v in violations:
        raw_hash = hashlib.sha256(
            f"{run_id}:{round_num}:{v.tech_id}:{v.prohibited_pattern_matched}".encode("utf-8")
        ).hexdigest()[:8]
        iss_id = f"ISSUE-TECH-{raw_hash}"

        filtered_rids = [r for r in v.related_req_ids if r in valid_task_requirements]
        if not filtered_rids:
            filtered_rids = [fallback_req]

        issue = Issue(
            id=iss_id,
            run_id=run_id,
            severity=v.severity,
            status=IssueStatus.OPEN,
            based_on_revision=base_revision,
            claim=v.claim,
            impact=v.impact,
            verification_request=f"Verify physical constraint compliance for {v.technology}: {v.prohibited_pattern_matched}",
            suggested_resolution=v.suggested_resolution,
            requirement_ids=filtered_rids,
        )
        issues.append(issue)

    return issues
