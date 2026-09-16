# API Design Rules

## Endpoint Structure
- Base: /api/v1/
- Tất cả response wrap trong: {"data": ..., "meta": {...}}
- Error response: {"error": {"message": "...", "code": "...", "details": {}}}

## Versioning
- Luôn có /api/v1/ prefix
- Breaking changes → tạo /api/v2/, KHÔNG xóa v1 ngay

## Request/Response
```python
# Mọi endpoint phải có schema rõ ràng
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    document_ids: Optional[List[str]] = None
    stream: bool = True

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    sources: List[DocumentSource]
    usage: TokenUsage
```

## Auth
- JWT Bearer token cho mọi endpoint trừ /health và /docs
- Rate limiting: 60 req/min per user, 10 req/min cho /upload

## Async
- Mọi endpoint PHẢI là async def
- File upload xử lý via background task (BackgroundTasks)

## Business account convention (external B2B signup)
- Role `"Doanh nghiệp"` (external business) đăng ký công khai qua `POST /api/auth/register-business` — tạo `User` với `approval_status="pending"`, KHÔNG trả token (không auto-login).
- `POST /api/auth/login` chặn (403) tài khoản `role == "Doanh nghiệp"` khi `approval_status` không phải `"approved"` — phân biệt message `"pending"` vs `"rejected"`.
- Admin duyệt/từ chối qua `PUT /api/admin/users/{id}/approval` (chỉ áp dụng cho role Doanh nghiệp, 400 nếu không phải).
- `User.approval_status` (`"pending"/"approved"/"rejected"`, `None` cho các role nội bộ) mirror convention của `Document.approval_status`.
- `POST /api/auth/login` cũng chặn (403) tài khoản Doanh nghiệp **đã** được duyệt, và chỉ sang cổng doanh nghiệp: cổng nội bộ không phải bề mặt của khách.
- Bề mặt bên ngoài nằm dưới `/api/v1/business/...`, sau `get_current_business_user` (yêu cầu claim `scope: "business"`, từ chối token `dev-skip`):
  `POST /auth/login`, `GET /me`, `POST /chat/stream` (SSE), `GET` và `DELETE /chat/history`, `POST /leads`.
  Chỉ bề mặt này dùng envelope `{"data", "meta"}`.
- `POST /chat/stream` nhận **chỉ** `{message}` với `extra="forbid"`; workspace, phạm vi tài liệu, retrieval mode và history đều do server quyết định.
  SSE event: `status`, `sources`, `delta`, `recommendations`, `lead_prompt`, `complete`, `error`.
- Gợi ý gói đi kèm trong **cùng một** LLM call: model kết câu trả lời bằng sentinel `[[GOI_Y: id1,id2,id3]]`, sentinel bị strip khỏi text hiển thị trước khi stream, id được validate lại với catalog đang active (id lạ hoặc inactive thì bỏ, cap 3), rồi phát event `recommendations`.
  Gợi ý luôn là phần cộng thêm: sentinel dở dang, id bịa hay lỗi đọc catalog đều thoái hoá thành "không có gợi ý", câu trả lời vẫn nguyên.
- Endpoint admin của portal: `PUT /api/v1/business/admin/workspaces/{id}/audience`, `GET /api/v1/business/admin/documents`, `PUT /api/v1/business/admin/documents/{id}/publish` (đều sau `require_admin`).
- Catalog gói: bảng `business_packages` (flat list, `category` là string; `price_note` là text tự do, cố ý không phải số). Chỉ row `is_active` mới vào prompt và mới được gợi ý.
  Chưa có admin CRUD: hiện populate bằng `seed_business_packages.py` (nội dung placeholder, chưa được sales duyệt).
- Chuyển lead cho sales (Phase 5) đã triển khai: khi ý định mua/ký rõ ràng, model kết câu trả lời bằng sentinel `[[LEAD: id1,id2|tóm tắt]]` (loại trừ với `[[GOI_Y:...]]`), server phát SSE event `lead_prompt` (chưa lưu DB, chỉ là bản nháp). Khách bấm xác nhận → `POST /leads` mới thật sự tạo `BusinessLead` (snapshot liên hệ từ `current_user`) và gọi `notify_lead_created` báo sales qua n8n/Telegram, tái dùng `N8N_WEBHOOK_URL` hiện có.
