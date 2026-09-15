# n8n AI Agent — trả lời email tự nhiên cho tài liệu chờ duyệt

**Status:** Approved
**Date:** 2026-09-12

## Bối cảnh

Luồng n8n hiện có (commit `9772a7b`..`de6428b`):
1. Upload → backend bắn webhook `document.uploaded` tới n8n (`app/services/n8n_webhook.py`).
2. n8n gửi email thông báo cho người có quyền duyệt.
3. Người duyệt phản hồi (qua cơ chế riêng của n8n) → n8n gọi `POST /api/v1/documents/{id}/approval-callback`, xác thực bằng header `X-Webhook-Secret` so khớp `N8N_CALLBACK_SECRET` (constant-time compare, fail-closed).
4. Backend duyệt/từ chối, kích hoạt ingest nếu duyệt.

Yêu cầu mới: người nhận mail thông báo có thể **reply bằng ngôn ngữ tự nhiên** ("tóm tắt giúp tôi", "tập trung vào mục X") thay vì chỉ approve/reject. n8n AI Agent hiểu yêu cầu, xử lý, rồi gửi lại email đính kèm PDF chứa kết quả.

## Mục tiêu / Không thuộc phạm vi

**Mục tiêu:** thêm 2 endpoint backend đóng vai trò "tool" cho AI Agent node của n8n:
- Lấy nội dung văn bản thô của tài liệu đang chờ duyệt.
- Render một đoạn markdown/text thành PDF để đính kèm email.

**Không thuộc phạm vi:**
- Thiết kế/triển khai workflow n8n (Gmail Trigger, AI Agent node, prompt) — đó là cấu hình bên n8n, không phải code repo này. Spec này chỉ nêu giả định cần thiết để n8n vận hành được.
- Không đụng đến `approval_status` hay trạng thái duyệt — tính năng này độc lập hoàn toàn với `approval-callback`.
- Không tái sử dụng pipeline NexusRAG/docling đầy đủ (quá nặng — pipeline đó gọi LLM để caption ảnh/bảng).
- Không hỗ trợ tóm tắt cho .pptx/.xlsx/.csv/ảnh ở giai đoạn này (trả `supported: false`, tương tự endpoint `/preview` hiện có).

## Kiến trúc

```
Email reply trong thread thông báo
        │
        ▼
n8n: Gmail Trigger (theo dõi thread) ──► AI Agent node (LLM riêng của n8n)
        │                                     │
        │                    gọi tool: GET /agent-content (lấy full text)
        │                                     │
        │                    AI Agent soạn nội dung trả lời
        │                                     │
        │                    gọi tool: POST /agent-report (text → PDF)
        ▼                                     ▼
   Gmail node: reply cùng thread, đính kèm PDF nhận về từ backend
```

Việc "hiểu ý định" (tóm tắt vs tập trung mục X) nằm hoàn toàn trong AI Agent node của n8n. Backend chỉ cung cấp dữ liệu thô và dịch vụ render PDF — không gọi LLM ở 2 endpoint mới này.

## Thành phần

### 1. Dependency xác thực dùng chung

`approval-callback` hiện inline logic:
```python
if not settings.N8N_CALLBACK_SECRET or not x_webhook_secret or not hmac.compare_digest(...):
    raise HTTPException(401, ...)
```
2 endpoint mới lặp lại y hệt logic này → tách thành dependency dùng chung `verify_n8n_webhook_secret` (đặt trong `app/core/deps.py`), `approval-callback` refactor để dùng lại dependency này. Tái sử dụng `N8N_CALLBACK_SECRET` đã có — không thêm secret mới (cùng một n8n instance, cùng ranh giới tin cậy đã chấp nhận cho quyết định duyệt/từ chối).

### 2. Text extractor nhẹ

Module mới `app/services/document_text_extractor.py`:
```python
async def extract_full_text(file_path: Path, file_type: str) -> ExtractedText:
    # ExtractedText: content: str | None, supported: bool, truncated: bool
```
- `.txt`, `.md`: đọc thẳng UTF-8.
- `.docx`: `python-docx`, nối toàn bộ paragraph (không giới hạn 30 đoạn như `/preview`).
- `.pdf`: PyMuPDF (`fitz`) — **dependency mới**, thêm `pymupdf>=1.24.0` vào `requirements.txt`.
- Khác: `supported=False`.
- Giới hạn `AGENT_CONTENT_MAX_CHARS = 20_000`; nếu vượt, cắt và đặt `truncated=True`.

### 3. `GET /api/v1/documents/{id}/agent-content`

Router mới `app/api/n8n_agent.py`, mount `/api/v1/documents`, tag `n8n-agent`.

- Header bắt buộc: `X-Webhook-Secret` (qua dependency ở trên).
- 404 nếu không tìm thấy document.
- 409 nếu `document.status != PENDING` (đã được xử lý xong bởi nhánh approve/reject hoặc đã ingest) — body `{"detail": "Document is no longer pending"}` để agent trả lời người dùng biết tài liệu không còn ở trạng thái chờ.
- 200 response (phẳng, không bọc `{"data","meta"}` — theo đúng tiền lệ `approval-callback` đã merge):
```json
{
  "id": 123,
  "filename": "bao_cao.pdf",
  "file_type": "pdf",
  "supported": true,
  "content": "...",
  "truncated": false
}
```
Khi `supported=false`: `content=null`, kèm `message` giải thích.

### 4. `POST /api/v1/documents/{id}/agent-report`

- Header: `X-Webhook-Secret`.
- Body (Pydantic): `{"title": str, "content_markdown": str}` (`content_markdown` không rỗng, `min_length=1`).
- Backend render PDF bằng `fpdf2` (pure Python, không cần thư viện hệ thống như cairo/pango — nhẹ hơn `weasyprint` cho Docker image) + font TTF hỗ trợ tiếng Việt (DejaVuSans, đóng gói trong `app/assets/fonts/DejaVuSans.ttf`). **Dependency mới**: `fpdf2>=2.7.0`.
- Trả `Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="tai_lieu_{document_id}_tom_tat.pdf"'})`.
- 401 nếu secret sai/thiếu (dependency dùng chung). 422 nếu `content_markdown` rỗng (Pydantic tự xử lý). 500 nếu render lỗi (log chi tiết, không nuốt lỗi).
- Endpoint này **không kiểm tra `document.status`** — chỉ cần document tồn tại (dùng để lấy `filename` gắn trong PDF/log audit), vì đây thuần là bước render, không phải bước đọc nội dung nhạy cảm mới.

## Giả định phía n8n (ngoài phạm vi code)

- Email thông báo gốc (do n8n soạn) phải chứa một định danh nhận diện được document_id (vd trong subject hoặc header tuỳ biến) để khi reply, n8n map lại đúng document. Đây là thay đổi cấu hình workflow n8n, không phải thay đổi backend.
- Trust boundary: bất kỳ ai có quyền truy cập hộp thư nhận thông báo đều được xem là có quyền hỏi nội dung tài liệu đó — cùng cơ chế xác thực (secret dùng chung) với approve/reject qua email hiện tại, nhưng **không phải cùng mức rủi ro**.
- **Blast radius tăng so với approve/reject**: trước tính năng này, secret bị lộ/đoán được chỉ cho phép approve/reject một document — một quyết định yes/no, không lộ nội dung. Từ tính năng này, cùng một secret còn cho phép đọc **toàn bộ nội dung văn bản gốc** của bất kỳ document PENDING nào, trên toàn tổ chức, bỏ qua hoàn toàn RBAC theo phòng ban/visibility vốn đang gate các endpoint `/documents/{id}/download` và `/preview` thông thường. Document id hiện là số tuần tự/dễ đoán, và app chưa có rate limiting. Vì vậy entropy của secret và chính sách xoay vòng (rotation) cần được xem xét lại tương xứng với mức độ nhạy cảm mới này, không chỉ dựa trên yêu cầu cũ của luồng approve/reject.

## Testing

Theo `.claude/rules/testing.md` (mock external calls, `test_db`, AAA, tên test mô tả hành vi):

- Unit: `document_text_extractor` — mỗi loại file (txt/md/docx/pdf/unsupported), trường hợp cắt do vượt `AGENT_CONTENT_MAX_CHARS`.
- Integration `agent-content`: thiếu secret → 401; sai secret → 401; document không tồn tại → 404; document không PENDING → 409; PENDING + docx → 200 có content; loại không hỗ trợ → 200 `supported=false`.
- Integration `agent-report`: thiếu secret → 401; `content_markdown` rỗng → 422; hợp lệ → 200 với `content-type: application/pdf` và body không rỗng.
- Refactor `verify_n8n_webhook_secret`: test hiện có của `approval-callback` (401 cases) phải tiếp tục pass nguyên vẹn sau khi refactor dùng dependency chung.

## Config bổ sung

- Không thêm secret mới — tái dùng `N8N_CALLBACK_SECRET`.
- `requirements.txt`: `+pymupdf>=1.24.0`, `+fpdf2>=2.7.0`.
- Hằng số mới: `AGENT_CONTENT_MAX_CHARS = 20_000`.
