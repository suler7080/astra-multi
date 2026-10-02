# Astra Multi

Môi trường cho các LLM coding phân tích độc lập, thảo luận có bằng chứng và tổng hợp kế hoạch triển khai có thể kiểm chứng.

## Tài liệu

- [PLAN.md](PLAN.md): kiến trúc đề xuất, giao thức thảo luận, mô hình dữ liệu, lộ trình triển khai và tiêu chí nghiệm thu.
- [PLAN_TEMPLATE.md](PLAN_TEMPLATE.md): mẫu đầu ra mà hệ thống sẽ tạo cho mỗi nhiệm vụ.
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md): thứ tự triển khai P0–P6, dependency, ma trận yêu cầu và prompt giao việc cho dev agent.
- [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md): task board và mẫu bàn giao tiến độ thực tế.
- [plans/](plans/): bảy plan giai đoạn, gồm 33 task có đầu ra và tiêu chí nghiệm thu.

## Trạng thái

Đã soạn thiết kế, chưa triển khai phần mềm. Ngày lập: 01/10/2026.

Để bắt đầu coding: đọc `IMPLEMENTATION_PLAN.md`, sau đó giao task **P0.1** trong `plans/P0_DISCOVERY_AND_SPIKE.md` cho dev agent.

Hướng đề xuất: **LangGraph + shared blackboard có cấu trúc + phản biện theo issue + quality gate bằng code**. Tái sử dụng framework ở những thành phần phù hợp; nghiệp vụ đảm bảo chất lượng kế hoạch được xây riêng.

Giả định khởi đầu: ứng dụng local-first trên Windows, một người dùng, tích hợp LLM qua API, có thể nhận repo hiện hữu hoặc yêu cầu xây mới. Các giả định cần xác nhận trước triển khai được liệt kê cuối PLAN.md.
