# Astra Multi

Môi trường cho các LLM coding phân tích độc lập, thảo luận có bằng chứng và tổng hợp kế hoạch triển khai có thể kiểm chứng.

## Tài liệu

- [PLAN.md](PLAN.md): kiến trúc đề xuất, giao thức thảo luận, mô hình dữ liệu, lộ trình triển khai và tiêu chí nghiệm thu.
- [PLAN_TEMPLATE.md](PLAN_TEMPLATE.md): mẫu đầu ra mà hệ thống sẽ tạo cho mỗi nhiệm vụ.
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md): thứ tự triển khai P0–P6, dependency, ma trận yêu cầu và prompt giao việc cho dev agent.
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md): task board và mẫu bàn giao tiến độ thực tế.
- [plans/](plans/): bảy plan giai đoạn, gồm 33 task có đầu ra và tiêu chí nghiệm thu.
- [docs/P1_CONTRACTS.md](docs/P1_CONTRACTS.md): public domain/repository API, revision/lease rules, schema samples và commands kiểm chứng.

## Trạng thái

P0 spike và P1 domain/persistence đã triển khai. P1 có canonical SQLite store, operation ledger, fenced leases và subprocess crash/recovery tests; xem [trạng thái kiểm chứng](IMPLEMENTATION_STATUS.md). P0.4 DONE theo phạm vi cập nhật: lưu key an toàn, provider tùy chỉnh, xKiro live và Windows Server 2022 native (254 passed, 4 skipped); direct OpenAI/Google live chưa chạy. UI và production orchestration/quality gate thuộc các phase sau.

Để tiếp tục coding: đọc `IMPLEMENTATION_PLAN.md`, dùng public contracts P1 để triển khai **P2.1 / P3.1**.

## API keys và provider tùy chỉnh

Hỗ trợ profile OpenAI, Google và endpoint OpenAI-compatible với model/base URL riêng. API key lưu trong OS credential store (Windows Credential Manager, macOS Keychain, Linux Secret Service/KWallet); environment-only hỗ trợ key tạm thời. Không ghi key vào JSON cấu hình.

Xem [hướng dẫn provider](docs/PROVIDER_CONFIGURATION.md) để cấu hình, rotate/xóa key và chạy live smoke bằng `python -m astra_multi.provider_smoke PROFILE`.

Hướng đề xuất: **LangGraph + shared blackboard có cấu trúc + phản biện theo issue + quality gate bằng code**. Tái sử dụng framework ở những thành phần phù hợp; nghiệp vụ đảm bảo chất lượng kế hoạch được xây riêng.

Giả định khởi đầu: ứng dụng local-first trên Windows, một người dùng, tích hợp LLM qua API, có thể nhận repo hiện hữu hoặc yêu cầu xây mới. Các giả định cần xác nhận trước triển khai được liệt kê cuối PLAN.md.
