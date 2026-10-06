import React, { createContext, useContext, useState } from 'react';

export type Language = 'EN' | 'VN';

export const translations = {
  EN: {
    // Header
    header_subtitle: 'Architecture Planner',
    header_run_label: 'Run:',
    header_select_placeholder: 'Select a run...',
    header_refresh_tooltip: 'Refresh runs and details',
    header_new_run: 'New Run',

    // Workflow / PhaseTracker
    phase_workflow_lifecycle: 'Workflow Lifecycle',
    phase_stop_reason: 'Stop reason:',
    status_final: 'FINAL',
    status_running: 'RUNNING',
    status_waiting: 'WAITING FOR INPUT',
    status_partial: 'PARTIAL',
    status_cancelled: 'CANCELLED',
    status_failed: 'FAILED',
    phase_intake: 'Intake',
    phase_snapshot: 'Snapshot',
    phase_investigate: 'Investigate',
    phase_independent_analysis: 'Analysis',
    phase_propose: 'Propose',
    phase_review: 'Review',
    phase_verify: 'Verify',
    phase_revise: 'Revise',
    phase_quality_gate: 'Quality Gate',
    phase_export: 'Export',

    // Navigation Tabs
    tab_overview: 'Overview',
    tab_discussion: 'Discussion',
    tab_issues: 'Issues',
    tab_decisions: 'Decisions',
    tab_evidence: 'Evidence',
    tab_plan: 'Plan Revisions',
    tab_logs: 'Execution Logs',
    tab_error_badge: 'Error',
    no_run_selected: 'No run selected. Create a new run or select an existing one.',

    // Feedback
    feedback_question_answered: 'Question answered. Deliberation continuing...',
    feedback_run_resumed: 'Run resumed.',
    feedback_run_cancelled: 'Run cancelled.',
    feedback_export_md_success: 'Exported Markdown.',
    feedback_export_json_success: 'Exported JSON.',

    // RunOverview
    overview_execution_stopped: 'Execution Stopped',
    overview_fatal_failure: 'Execution Failure',
    overview_view_logs: 'View Error Logs',
    overview_clarification_title: 'Clarification Needed from Operator',
    overview_question_count: 'Question(s)',
    overview_clarification_desc: 'The agents have paused deliberation to request specific human input or decision constraint:',
    overview_answer_placeholder: 'Provide answer / architectural preference...',
    overview_submit: 'Submit',
    overview_all_answered: 'All questions answered? Resume deliberation to continue planning:',
    overview_resume_run: 'Resume Run',
    overview_goal: 'Goal & Objective',
    overview_status_rev: 'Status & Revision',
    overview_artifacts: 'Artifacts Committed',
    overview_plans_count: 'Plans:',
    overview_issues_count: 'Issues:',
    overview_blocking: 'blocking',
    overview_decisions_count: 'Decisions:',
    overview_evidence_count: 'Evidence:',
    overview_target_requirements: 'Target Requirements',
    overview_acceptance: 'Acceptance:',
    overview_cancel_run: 'Cancel Run',
    overview_confirm_stop: 'Confirm Stop',
    overview_cancel_placeholder: 'Reason for cancellation...',
    overview_cancel: 'Cancel',
    overview_validate_gates: 'Validate Quality Gates',
    overview_finalize_plan: 'Finalize Plan',
    overview_export_md: 'Export Markdown',
    overview_export_json: 'Export JSON',

    // Execution Logs
    logs_title: 'Execution Logs',
    logs_stopped_fatal: 'Execution Stopped: Fatal Failure',
    logs_copy_error: 'Copy Error Details',
    logs_copied: 'Copied',
    logs_filter_all: 'All',
    logs_filter_error: 'Errors',
    logs_filter_warn: 'Warnings',
    logs_filter_info: 'Info',
    logs_search_placeholder: 'Search logs...',
    logs_live_stream: 'Live Stream',
    logs_refresh: 'Refresh',
    logs_copy_logs: 'Copy Logs',
    logs_no_match: 'No log entries match the current filter criteria.',
    logs_no_logs: 'No execution logs recorded yet.',
    logs_diagnostics_title: 'Payload & Execution Diagnostics',
    logs_stack_trace: 'Stack Trace:',
    logs_copy_json: 'Copy JSON',

    // New Run Modal
    modal_new_run_title: 'New Architecture Run',
    modal_goal_label: 'Architecture Task Goal',
    modal_goal_placeholder: 'e.g. Design high-throughput distributed event broker...',
    modal_requirements_label: 'Target Requirements & Constraints',
    modal_add_requirement: 'Add Requirement',
    modal_execution_limits: 'Execution & Budget Limits',
    modal_max_rounds: 'Max Deliberation Rounds',
    modal_token_limit: 'Token Limit (0 = unlimited)',
    modal_cost_limit: 'Cost Limit USD ($0 = unlimited)',
    modal_btn_cancel: 'Cancel',
    modal_btn_create: 'Start Deliberation',
    modal_btn_creating: 'Starting Run...',

    // Quality Gate Modal
    qg_validation_title: 'P4 Quality Gates Structural Validation',
    qg_finalize_title: 'Finalization Evaluation Result',
    qg_passed: 'PASSED',
    qg_failed: 'FAILED',
    qg_violations: 'Quality Violations',
    qg_uncovered_reqs: 'Uncovered Requirements',
    qg_unresolved_issues: 'Unresolved Blocking Issues',
    qg_close: 'Close',

    // Details tabs
    timeline_title: 'Discussion Timeline',
    timeline_connected: 'Live Connected',
    timeline_disconnected: 'Disconnected',
    timeline_empty: 'No events received yet. Deliberation is starting...',
    issues_title: 'Issues Register',
    issues_empty: 'No issues recorded for this run.',
    decisions_title: 'Architectural Decisions',
    decisions_empty: 'No architectural decisions recorded yet.',
    evidence_title: 'Evidence Ledger',
    evidence_empty: 'No evidence items captured.',
    plan_title: 'Plan Revision',
    plan_no_plan: 'No plan revision has been committed yet.',
    plan_steps: 'Execution Steps',
    plan_decisions: 'Key Decisions',
    plan_risks: 'Identified Risks',

    // Auth & Security
    auth_login_title: 'Admin Access Required',
    auth_login_subtitle: 'Enter your administrative password to access the workbench.',
    auth_setup_title: 'Initial Security Setup',
    auth_setup_subtitle: 'Set an administrative password to protect your API keys and runs.',
    auth_password_label: 'Admin Password',
    auth_password_placeholder: 'Enter at least 4 characters...',
    auth_confirm_password_label: 'Confirm Password',
    auth_confirm_password_placeholder: 'Re-enter password...',
    auth_btn_login: 'Log In',
    auth_btn_setup: 'Set Password & Continue',
    auth_btn_logout: 'Log Out',
    auth_error_mismatch: 'Passwords do not match.',
    auth_error_too_short: 'Password must be at least 4 characters.',

    // Settings Modal
    settings_title: 'System & LLM Settings',
    settings_tab_providers: 'LLM Providers & Models',
    settings_tab_security: 'Admin Security',
    settings_active_badge: 'ACTIVE PROVIDER',
    settings_add_provider: 'Add Provider Profile',
    settings_edit_provider: 'Edit Profile',
    settings_provider_name: 'Profile Name',
    settings_provider_kind: 'Provider Type',
    settings_base_url: 'Base URL (Endpoint)',
    settings_model: 'Model Name / ID',
    settings_api_key: 'API Key (Secret)',
    settings_api_key_placeholder: 'Leave blank to preserve existing key...',
    settings_btn_test: 'Test Connection',
    settings_btn_testing: 'Testing...',
    settings_test_success: 'Connected successfully',
    settings_test_failed: 'Connection failed',
    settings_btn_activate: 'Set as Active',
    settings_btn_activated: 'Active',
    settings_btn_delete: 'Delete Profile',
    settings_btn_save: 'Save Profile',
    settings_current_password: 'Current Password',
    settings_new_password: 'New Password',
    settings_btn_change_password: 'Update Password',
    settings_password_updated: 'Password updated successfully!',
    header_btn_settings: 'Settings',

    // Dashboard Home
    dash_welcome_title: 'Architecture Deliberation Dashboard',
    dash_welcome_subtitle: 'Multi-agent collaborative software architecture planning, evaluation & quality validation workbench.',
    dash_total_runs: 'Total Runs',
    dash_active_runs: 'Deliberating / Active',
    dash_final_runs: 'Finalized Architecture',
    dash_failed_runs: 'Needs Review',
    dash_recent_runs: 'Recent Architecture Runs',
    dash_no_runs_desc: 'No architecture deliberation runs found. Click "+ New Run" to start your first task.',
    dash_btn_open_run: 'Open Run',
    dash_col_goal: 'Task Objective',
    dash_col_status: 'Lifecycle Status',
    dash_col_revision: 'Revision',
    dash_col_created: 'Started At',
    header_all_runs: '⬅ All Runs (Dashboard)',
  },
  VN: {
    // Header
    header_subtitle: 'Bộ lập kế hoạch kiến trúc',
    header_run_label: 'Phiên:',
    header_select_placeholder: 'Chọn phiên làm việc...',
    header_refresh_tooltip: 'Làm mới danh sách và chi tiết',
    header_new_run: 'Tạo phiên mới',

    // Workflow / PhaseTracker
    phase_workflow_lifecycle: 'Vòng đời quy trình',
    phase_stop_reason: 'Lý do dừng:',
    status_final: 'HOÀN TẤT',
    status_running: 'ĐANG CHẠY',
    status_waiting: 'CHỜ PHẢN HỒI',
    status_partial: 'MỘT PHẦN',
    status_cancelled: 'ĐÃ HỦY',
    status_failed: 'THẤT BẠI',
    phase_intake: 'Tiếp nhận',
    phase_snapshot: 'Chụp trạng thái',
    phase_investigate: 'Khảo sát',
    phase_independent_analysis: 'Phân tích',
    phase_propose: 'Đề xuất',
    phase_review: 'Phản biện',
    phase_verify: 'Kiểm chứng',
    phase_revise: 'Hoàn thiện',
    phase_quality_gate: 'Cổng chất lượng',
    phase_export: 'Xuất kết quả',

    // Navigation Tabs
    tab_overview: 'Tổng quan',
    tab_discussion: 'Thảo luận',
    tab_issues: 'Vấn đề',
    tab_decisions: 'Quyết định',
    tab_evidence: 'Bằng chứng',
    tab_plan: 'Bản kế hoạch',
    tab_logs: 'Nhật ký thực thi',
    tab_error_badge: 'Lỗi',
    no_run_selected: 'Chưa chọn phiên làm việc. Hãy tạo phiên mới hoặc chọn phiên có sẵn.',

    // Feedback
    feedback_question_answered: 'Đã gửi câu trả lời. Quá trình thảo luận đang tiếp tục...',
    feedback_run_resumed: 'Đã tiếp tục phiên làm việc.',
    feedback_run_cancelled: 'Đã hủy phiên làm việc.',
    feedback_export_md_success: 'Đã xuất Markdown thành công.',
    feedback_export_json_success: 'Đã xuất JSON thành công.',

    // RunOverview
    overview_execution_stopped: 'Thực thi bị dừng',
    overview_fatal_failure: 'Thực thi thất bại',
    overview_view_logs: 'Xem nhật ký lỗi',
    overview_clarification_title: 'Cần người vận hành làm rõ',
    overview_question_count: 'Câu hỏi',
    overview_clarification_desc: 'Các agent đã tạm dừng thảo luận để yêu cầu thông tin hoặc quyết định từ con người:',
    overview_answer_placeholder: 'Nhập câu trả lời / yêu cầu kiến trúc...',
    overview_submit: 'Gửi',
    overview_all_answered: 'Đã trả lời xong? Tiếp tục thảo luận để lập kế hoạch:',
    overview_resume_run: 'Tiếp tục chạy',
    overview_goal: 'Mục tiêu & Yêu cầu',
    overview_status_rev: 'Trạng thái & Phiên bản',
    overview_artifacts: 'Hiện vật đã ghi nhận',
    overview_plans_count: 'Kế hoạch:',
    overview_issues_count: 'Vấn đề:',
    overview_blocking: 'chặn tiến độ',
    overview_decisions_count: 'Quyết định:',
    overview_evidence_count: 'Bằng chứng:',
    overview_target_requirements: 'Yêu cầu mục tiêu',
    overview_acceptance: 'Tiêu chuẩn nghiệm thu:',
    overview_cancel_run: 'Hủy phiên',
    overview_confirm_stop: 'Xác nhận dừng',
    overview_cancel_placeholder: 'Lý do hủy phiên...',
    overview_cancel: 'Hủy',
    overview_validate_gates: 'Kiểm tra chất lượng',
    overview_finalize_plan: 'Chốt kế hoạch (Finalize)',
    overview_export_md: 'Xuất Markdown',
    overview_export_json: 'Xuất JSON',

    // Execution Logs
    logs_title: 'Nhật ký thực thi',
    logs_stopped_fatal: 'Thực thi thất bại nghiêm trọng',
    logs_copy_error: 'Sao chép chi tiết lỗi',
    logs_copied: 'Đã sao chép',
    logs_filter_all: 'Tất cả',
    logs_filter_error: 'Lỗi',
    logs_filter_warn: 'Cảnh báo',
    logs_filter_info: 'Thông tin',
    logs_search_placeholder: 'Tìm kiếm nhật ký...',
    logs_live_stream: 'Trực tiếp',
    logs_refresh: 'Làm mới',
    logs_copy_logs: 'Sao chép nhật ký',
    logs_no_match: 'Không có mục nhật ký nào khớp bộ lọc.',
    logs_no_logs: 'Chưa có nhật ký nào được ghi nhận.',
    logs_diagnostics_title: 'Dữ liệu & Chẩn đoán thực thi',
    logs_stack_trace: 'Ngăn xếp lỗi (Stack Trace):',
    logs_copy_json: 'Sao chép JSON',

    // New Run Modal
    modal_new_run_title: 'Tạo phiên lập kế hoạch mới',
    modal_goal_label: 'Mục tiêu bài toán kiến trúc',
    modal_goal_placeholder: 'ví dụ: Thiết kế hệ thống phân tán chịu tải cao...',
    modal_requirements_label: 'Các yêu cầu & Ràng buộc',
    modal_add_requirement: 'Thêm yêu cầu',
    modal_execution_limits: 'Giới hạn thực thi & Chi phí',
    modal_max_rounds: 'Số vòng thảo luận tối đa',
    modal_token_limit: 'Giới hạn Token (0 = không giới hạn)',
    modal_cost_limit: 'Giới hạn chi phí USD (0 = không giới hạn)',
    modal_btn_cancel: 'Hủy',
    modal_btn_create: 'Bắt đầu thảo luận',
    modal_btn_creating: 'Đang khởi tạo...',

    // Quality Gate Modal
    qg_validation_title: 'Kiểm tra cấu trúc cổng chất lượng P4',
    qg_finalize_title: 'Kết quả thẩm định chốt kế hoạch',
    qg_passed: 'ĐẠT',
    qg_failed: 'CHƯA ĐẠT',
    qg_violations: 'Vi phạm quy tắc chất lượng',
    qg_uncovered_reqs: 'Yêu cầu chưa được bao quát',
    qg_unresolved_issues: 'Vấn đề chặn chưa giải quyết',
    qg_close: 'Đóng',

    // Details tabs
    timeline_title: 'Dòng thời gian thảo luận',
    timeline_connected: 'Đã kết nối trực tiếp',
    timeline_disconnected: 'Mất kết nối',
    timeline_empty: 'Chưa có sự kiện nào. Quá trình thảo luận đang bắt đầu...',
    issues_title: 'Danh sách vấn đề phát hiện',
    issues_empty: 'Chưa có vấn đề nào được ghi nhận cho phiên này.',
    decisions_title: 'Các quyết định kiến trúc',
    decisions_empty: 'Chưa có quyết định kiến trúc nào được ghi nhận.',
    evidence_title: 'Sổ cái bằng chứng',
    evidence_empty: 'Chưa có bằng chứng nào được thu thập.',
    plan_title: 'Bản kế hoạch kiến trúc',
    plan_no_plan: 'Chưa có bản kế hoạch nào được ghi nhận.',
    plan_steps: 'Các bước triển khai',
    plan_decisions: 'Quyết định cốt lõi',
    plan_risks: 'Rủi ro nhận diện',

    // Auth & Security
    auth_login_title: 'Yêu cầu xác thực Admin',
    auth_login_subtitle: 'Nhập mật khẩu quản trị để truy cập bảng điều khiển.',
    auth_setup_title: 'Thiết lập bảo mật ban đầu',
    auth_setup_subtitle: 'Cài đặt mật khẩu quản trị để bảo vệ API key và các phiên chạy.',
    auth_password_label: 'Mật khẩu Admin',
    auth_password_placeholder: 'Nhập tối thiểu 4 ký tự...',
    auth_confirm_password_label: 'Xác nhận mật khẩu',
    auth_confirm_password_placeholder: 'Nhập lại mật khẩu...',
    auth_btn_login: 'Đăng nhập',
    auth_btn_setup: 'Lưu mật khẩu & Tiếp tục',
    auth_btn_logout: 'Đăng xuất',
    auth_error_mismatch: 'Mật khẩu xác nhận không khớp.',
    auth_error_too_short: 'Mật khẩu phải có ít nhất 4 ký tự.',

    // Settings Modal
    settings_title: 'Cấu hình hệ thống & Mô hình LLM',
    settings_tab_providers: 'Nhà cung cấp & Mô hình LLM',
    settings_tab_security: 'Bảo mật Admin',
    settings_active_badge: 'MÔ HÌNH ĐANG DÙNG',
    settings_add_provider: 'Thêm cấu hình Provider',
    settings_edit_provider: 'Sửa cấu hình',
    settings_provider_name: 'Tên cấu hình',
    settings_provider_kind: 'Loại Provider',
    settings_base_url: 'Base URL (Endpoint)',
    settings_model: 'Tên / ID Mô hình',
    settings_api_key: 'API Key (Mật mã)',
    settings_api_key_placeholder: 'Để trống nếu muốn giữ nguyên key cũ...',
    settings_btn_test: 'Kiểm tra kết nối',
    settings_btn_testing: 'Đang kiểm tra...',
    settings_test_success: 'Kết nối thành công',
    settings_test_failed: 'Kết nối thất bại',
    settings_btn_activate: 'Đặt làm mặc định',
    settings_btn_activated: 'Đang kích hoạt',
    settings_btn_delete: 'Xóa cấu hình',
    settings_btn_save: 'Lưu cấu hình',
    settings_current_password: 'Mật khẩu hiện tại',
    settings_new_password: 'Mật khẩu mới',
    settings_btn_change_password: 'Đổi mật khẩu',
    settings_password_updated: 'Đã đổi mật khẩu thành công!',
    header_btn_settings: 'Cài đặt',

    // Dashboard Home
    dash_welcome_title: 'Bảng điều khiển Thiết kế Kiến trúc',
    dash_welcome_subtitle: 'Hệ thống cộng tác đa tác tử AI thiết kế, lập kế hoạch và thẩm định kiến trúc phần mềm.',
    dash_total_runs: 'Tổng số phiên',
    dash_active_runs: 'Đang thảo luận',
    dash_final_runs: 'Đã hoàn tất',
    dash_failed_runs: 'Cần kiểm tra',
    dash_recent_runs: 'Danh sách các phiên làm việc',
    dash_no_runs_desc: 'Chưa có phiên làm việc nào. Bấm nút "+ Tạo phiên mới" để bắt đầu bài toán thiết kế.',
    dash_btn_open_run: 'Vào phiên làm việc',
    dash_col_goal: 'Mục tiêu bài toán',
    dash_col_status: 'Trạng thái quy trình',
    dash_col_revision: 'Phiên bản',
    dash_col_created: 'Khởi tạo lúc',
    header_all_runs: '⬅ Tất cả phiên (Trang chủ)',
  },
} as const;

export type TranslationKey = keyof typeof translations.EN;

interface I18nContextType {
  lang: Language;
  setLang: (lang: Language) => void;
  t: (key: TranslationKey, fallback?: string) => string;
}

const I18nContext = createContext<I18nContextType>({
  lang: 'VN',
  setLang: () => {},
  t: (key: TranslationKey, fallback?: string) => fallback || key,
});

export const I18nProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lang, setLangState] = useState<Language>(() => {
    const saved = localStorage.getItem('astra_lang');
    return saved === 'EN' || saved === 'VN' ? saved : 'VN';
  });

  const setLang = (newLang: Language) => {
    setLangState(newLang);
    localStorage.setItem('astra_lang', newLang);
  };

  const t = (key: TranslationKey, fallback?: string): string => {
    const currentDict = translations[lang];
    if (key in currentDict) {
      return currentDict[key];
    }
    return fallback || key;
  };

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
};

export const useI18n = () => useContext(I18nContext);

export const LanguageSwitcher: React.FC<{ className?: string }> = ({ className = '' }) => {
  const { lang, setLang } = useI18n();

  return (
    <div className={`lang-switcher-container ${className}`}>
      <button
        type="button"
        onClick={() => setLang('EN')}
        className={`lang-btn ${lang === 'EN' ? 'lang-btn-active' : ''}`}
        title="Switch to English"
      >
        <span className="lang-flag">🇬🇧</span>
        <span>ENG</span>
      </button>
      <button
        type="button"
        onClick={() => setLang('VN')}
        className={`lang-btn ${lang === 'VN' ? 'lang-btn-active' : ''}`}
        title="Chuyển sang Tiếng Việt"
      >
        <span className="lang-flag">🇻🇳</span>
        <span>VN</span>
      </button>
    </div>
  );
};
