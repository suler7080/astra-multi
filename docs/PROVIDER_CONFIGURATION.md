# Provider profiles và API key

## Cấu hình

`generate(provider="openai", ...)` và `generate(provider="google", ...)` vẫn hoạt động với biến môi trường cũ. Thêm provider có giao thức OpenAI-compatible bằng một **profile đặt tên** chứa `kind`, `model`, `base_url`, tùy chọn JSON mode và tham chiếu credential; gọi `generate(provider="xkiro", ...)` để chọn profile.

Key lưu lâu dài dùng **Windows Credential Manager**, macOS Keychain hoặc Linux Secret Service/KWallet qua keyring 25.6.0. JSON chỉ lưu metadata, không chứa key. Không dùng plaintext keyring/fallback tự động. Linux headless chưa có keyring phải dùng chế độ environment-only hoặc cấu hình/unlock OS keyring. Đây là CLI/backend; màn hình quản lý provider thuộc P5.

Trong `backend`, cài dependencies từ lock UTF-8 có platform markers và editable project:

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.lock -e '.[dev,providers]'
```

Linux dùng `.venv/bin/python`. LangGraph 0.6.11 và checkpoint-sqlite 2.0.11 được giữ nguyên. Lock được tái tạo bằng `uv pip compile pyproject.toml --extra dev --extra providers --python-version 3.11 --universal --output-file requirements.lock`, thay cho lock UTF-16 cũ chứa đường dẫn editable của một máy Windows.

## Lưu key trong OS credential store

Lệnh `set` hỏi key bằng input ẩn, không đưa giá trị key vào command line/shell history:

```powershell
.venv/Scripts/python.exe -m astra_multi.provider_cli set xkiro --kind openai-compatible --model 'qwen/qwen3.8-omni-flash:free' --base-url 'https://api.xkiro.com/v1'
.venv/Scripts/python.exe -m astra_multi.provider_cli set openai --kind openai --model 'gpt-4o-mini' --base-url 'https://api.openai.com/v1'
.venv/Scripts/python.exe -m astra_multi.provider_cli set google --kind google --model 'gemini-2.0-flash'
.venv/Scripts/python.exe -m astra_multi.provider_cli list
```

`list` chỉ xuất metadata. Credential service là `AstraMulti/provider-api-key`, username là tên profile. Chạy lại `set` cùng tên để đổi key hoặc model/base URL; key không phải thuộc tính của domain/run/checkpoint. Nếu ghi metadata thất bại sau khi thay key, manager thử khôi phục key cũ; hai storage không có chung transaction, nên việc rollback cũng có thể thất bại nếu keyring mất kết nối. Không có cam kết atomicity qua hai hệ thống.

```powershell
.venv/Scripts/python.exe -m astra_multi.provider_cli remove xkiro
```

`remove` với profile OS xóa cả credential và override. Xóa override `openai`/`google` khôi phục profile builtin để tương thích biến môi trường cũ.

## Key tạm thời / automation

Nếu đã được provision qua môi trường an toàn, chỉ cung cấp **tên biến**, không truyền key trực tiếp làm tham số:

```powershell
.venv/Scripts/python.exe -m astra_multi.provider_cli set xkiro --kind openai-compatible --model 'qwen/qwen3.8-omni-flash:free' --base-url 'https://api.xkiro.com/v1' --key-env ASTRA_PROVIDER_TEST_API_KEY --env-only
```

`--env-only` chỉ lưu tên biến và `credential_source="environment"`; không ghi OS credential và không fallback về key OS khi biến không tồn tại. Profile môi trường có thể xóa ngay cả khi máy không có keyring. Xóa metadata không thể xóa biến môi trường của shell cha. Nếu trước đó có key OS cùng tên, chuyển sang environment-only không xóa key OS cũ; xóa profile OS trước khi chuyển nếu muốn loại bỏ credential cũ.

Không có `--env-only`, `--key-env NAME` đọc biến đó để lưu key vào OS store. Khi profile OS có `api_key_env`, giá trị môi trường không rỗng được ưu tiên, rồi mới đến OS store. Muốn chỉ dùng key đã lưu, cấu hình profile bằng input ẩn và không thêm `--key-env`.

File cấu hình mặc định:

- Windows: `%APPDATA%/AstraMulti/providers.json`.
- Linux: `$XDG_CONFIG_HOME/AstraMulti/providers.json`, mặc định `~/.config/AstraMulti/providers.json`.
- macOS: `~/Library/Application Support/AstraMulti/providers.json`.
- `ASTRA_PROVIDER_CONFIG` hoặc CLI `--config PATH` chọn một file khác. Python API có thể inject `ProviderSettingsRepository` và `CredentialStore`.

Custom base URL phải HTTPS (HTTP chỉ cho loopback), không chứa user/password, query hoặc fragment. Profile có URL riêng không dùng `OPENAI_BASE_URL` của profile khác. Profile builtin OpenAI chưa ghi URL vẫn giữ hành vi SDK cũ với `OPENAI_BASE_URL`.

## JSON, errors và smoke

Pydantic `output_schema` được validate sau parse **ngay trong adapter**. Schema dạng string cũ vẫn được parse JSON; dùng `type[BaseModel]` để enforce đầy đủ. Nếu endpoint không hỗ trợ JSON mode, thêm `--no-json-mode` để chỉ dùng schema trong prompt và kiểm tra local; output sai luôn trả `SchemaError`, không tự sửa vô hạn. Google cũng dùng JSON MIME/prompt cùng kiểm tra local vì Gemini native schema có thể không hỗ trợ mọi constraint Pydantic.

ModelResult trả tên profile, model ID từ phản hồi nếu có, usage và latency của adapter. Usage thiếu giữ `None`/unknown. Retry SDK giới hạn bởi `max_retries`, mặc định 0; `attempts` chỉ biết là 1 khi không retry, còn khi bật retry là unknown. Usage/cost budget hooks và capability registry đầy đủ vẫn thuộc P3.

Smoke chỉ chạy khi gọi rõ ràng; tối đa một text và một JSON request cho mỗi model liệt kê, timeout 30 giây, retry 0:

```powershell
.venv/Scripts/python.exe -m astra_multi.provider_smoke xkiro --model 'qwen/qwen3.8-omni-flash:free' --model 'qwen/qwen3.8-max:free' --output '.local/xkiro-live.json'
```

Report chứa response đúng smoke, model, usage, latency và error code; không chứa credential hay failed response bodies. Đây là kiểm tra tích hợp API, không đánh giá chất lượng production workflow hoặc chứng minh model routing của gateway độc lập. Các test live OpenAI/Google gốc vẫn opt-in theo credential tương ứng.

## Offline và native Windows verification

```powershell
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/mypy.exe
.venv/Scripts/ruff.exe check src/astra_multi/providers.py src/astra_multi/provider_config.py src/astra_multi/credentials.py src/astra_multi/provider_cli.py src/astra_multi/provider_smoke.py tests/unit/test_provider_settings.py
```

`test_windows_native_credential_store_restart_rotation_removal` chỉ chạy trên Windows thật: set key tổng hợp, đọc ở process mới, rotate, remove và kiểm tra cleanup. Các contract tests dùng HTTPX MockTransport với SDK OpenAI/Google thật để xác nhận endpoint, header, schema, timeout và lỗi; không tiêu API budget. Crash/recovery dùng subprocess kill thực, không thay bằng mock.
