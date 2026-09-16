# Cổng B2B — yêu cầu báo giá/hợp đồng, chuyển lead cho sales (Phase 5)

**Status:** Approved
**Date:** 2026-09-15

## Bối cảnh

Cổng B2B hiện tại (`app/api/business_chat.py`, `app/services/business_chat.py`) đã trả lời khách hàng dựa trên tài liệu công bố, và gợi ý gói phù hợp qua cơ chế sentinel trong chính câu trả lời: khi nhu cầu khách còn rộng, LLM kết thúc câu trả lời bằng `[[GOI_Y: id1,id2,id3]]`, `RecommendationSentinelFilter` strip sentinel này khỏi luồng hiển thị và server phát SSE event `recommendations`.

Việc "khách bấm vào gợi ý để làm gì tiếp theo" đã được để ngỏ có chủ đích:
- `BusinessPackageCards.jsx` (frontend): *"Deliberately not clickable yet: acting on a suggestion is Phase 5"*.
- `businessApi.js`: switch xử lý SSE event đã có comment *"Phase 5 adds `lead_prompt`. Unknown events are ignored, never shown."*
- `.claude/rules/api-design.md`: *"CHƯA triển khai: chuyển lead cho sales (Phase 5)."*

Đây chính là Phase 5 đó. Không phải chuyển toàn bộ hệ thống thành sàn đa doanh nghiệp (đã xác nhận với người dùng: cổng vẫn phục vụ một công ty — Micco — không có khái niệm tenant/organization), mà là cho khách hàng ngoài có thể **bày tỏ ý định mua/ký hợp đồng ngay trong hội thoại**, và hệ thống chuyển thông tin đó cho sales người thật xử lý, tự động hoá bước thông báo qua n8n (kênh Telegram đang dùng cho luồng duyệt tài liệu).

## Mục tiêu / Không thuộc phạm vi

**Mục tiêu:**
- LLM phát hiện ý định thương mại rõ ràng (muốn mua/ký hợp đồng, không chỉ hỏi thông tin) và đề xuất tạo yêu cầu gửi sales, kèm tóm tắt nhu cầu (kể cả ngân sách nếu khách có nêu) và (nếu có) các gói liên quan.
- Khách hàng phải **bấm xác nhận** trước khi yêu cầu thực sự được gửi đi — không tự động gửi chỉ vì LLM đoán ý định.
- Yêu cầu đã xác nhận được lưu lại (`business_leads`) và n8n báo cho sales qua kênh Telegram hiện có.

**Không thuộc phạm vi:**
- Đa doanh nghiệp/multi-tenant (nhiều công ty khác Micco tự có catalog/workspace riêng) — ngoài phạm vi, không đụng tới.
- Sinh báo giá/hợp đồng tự động, tính giá — giá/điều khoản do sales xác nhận, đúng nguyên tắc đã có trong `BUSINESS_SYSTEM_PROMPT`.
- Theo dõi trạng thái lead (mới/đang liên hệ/đã chốt), dashboard quản lý lead — theo lựa chọn của người dùng, chỉ lưu để audit.
- Kênh thông báo mới hay secret mới cho n8n — tái dùng `N8N_WEBHOOK_URL` đã có.
- Tích hợp với sàn TMĐT B2B bên thứ ba — không nằm trong yêu cầu đã xác nhận.

## Kiến trúc

```
Khách nhắn ý định mua/ký hợp đồng
        │
        ▼
stream_business_chat() ──► LLM trả lời + kết thúc bằng
                            [[LEAD: id1,id2|tóm tắt nhu cầu]]
        │
        ▼
LeadSentinelFilter.feed()  (mới, sau RecommendationSentinelFilter trong pipeline)
   strip sentinel khỏi text hiển thị, parse ids + tóm tắt
        │
        ▼
SSE event mới: lead_prompt {summary, packages}   ← chưa lưu DB
        │
        ▼
Frontend: BusinessLeadPrompt hiện thẻ xác nhận dưới câu trả lời
        │  (khách bấm "Gửi yêu cầu")
        ▼
POST /api/v1/business/leads {summary, package_ids}
        │
        ▼
Lưu BusinessLead  ──►  BackgroundTasks: notify_lead_created()
                              │
                              ▼
                        POST N8N_WEBHOOK_URL {"event": "lead.created", ...}
                              │
                              ▼
                    n8n (ngoài repo): branch theo event → Telegram group sales
```

Hai sentinel (`[[GOI_Y:`, `[[LEAD:`) độc lập với nhau và không cùng xuất hiện trong một câu trả lời — prompt sẽ nêu rõ đây là hai nhánh loại trừ nhau (nhu cầu còn rộng → gợi ý gói; ý định mua/ký rõ ràng → đề xuất gửi sales). Về mặt kỹ thuật, hai `SentinelFilter` được nối tiếp trong pipeline (`RecommendationSentinelFilter.feed()` → `LeadSentinelFilter.feed()`) nên vẫn đúng dù có xuất hiện cùng lúc: mỗi filter chỉ có trách nhiệm không để lộ marker của chính nó, filter sau vẫn tự đệm dữ liệu nhận được từ filter trước.

## Thành phần

### 1. Model + migration — `BusinessLead`

`app/models/business_lead.py`, migration `012_add_business_leads.py`:

```python
class BusinessLead(Base):
    __tablename__ = "business_leads"

    id: Mapped[int]
    business_user_id: Mapped[int]  # FK users.id, ondelete SET NULL — lead vẫn còn nếu tài khoản bị xoá
    company_name: Mapped[str | None]   # snapshot tại thời điểm tạo lead
    contact_phone: Mapped[str | None]  # snapshot
    contact_email: Mapped[str]         # snapshot — users.email NOT NULL nên luôn có
    summary: Mapped[str]               # Text — tóm tắt nhu cầu (kể cả ngân sách, nếu khách nêu)
    package_ids: Mapped[list | None]   # JSON — id các gói liên quan, đã validate với catalog active
    created_at: Mapped[datetime]
```

Snapshot liên hệ (không JOIN sang `users` khi đọc lại) theo đúng lý do đã nêu ban đầu: hồ sơ khách có thể đổi sau, lead phải giữ nguyên thông tin tại thời điểm gửi.

Không có `budget_note` riêng như phác thảo ban đầu — gộp vào `summary` (LLM viết một đoạn tóm tắt tự nhiên bao gồm cả ngân sách nếu khách có nói), để tránh phải parse một delimiter thứ hai trong sentinel một cách mong manh. Đơn giản hơn, không mất thông tin.

### 2. `LeadSentinelFilter` — `app/services/business_lead_sentinel.py`

Sinh đôi với `RecommendationSentinelFilter`, cùng kỹ thuật đệm safe-prefix, không tái dùng chung class (đúng lý do đã ghi trong docstring của module gốc: cần fail-closed riêng cho từng loại sentinel).

- Marker: `SENTINEL_OPEN = "[[LEAD:"`, `SENTINEL_CLOSE = "]]"`.
- Thân sentinel: `<id1,id2,id3 hoặc rỗng>|<tóm tắt nhu cầu>` — tách tại dấu `|` **đầu tiên**; phần ids parse bằng regex số như `RecommendationSentinelFilter`, phần còn lại (có thể chứa `|` khác) là `summary`, trim khoảng trắng.
- Thiếu dấu `|` trong thân → coi là sentinel hỏng, fail-closed: không có lead, không emit gì thêm (giống case "unterminated sentinel" hiện có — log rồi bỏ).
- Cận trên thân sentinel: `_MAX_SENTINEL_BODY = 600` (tóm tắt nhu cầu dài hơn "id1,id2,id3" của gợi ý gói, nên cận cao hơn 200 của `RecommendationSentinelFilter`) — vượt cận thì coi như không phải sentinel thật, trả lại nguyên văn cho khách đọc (giống hệt cơ chế overflow đã có).
- API: `feed(text) -> str`, `finish() -> tuple[str, LeadDraft | None]` với `LeadDraft = namedtuple("LeadDraft", "summary package_ids")` (hoặc `None` nếu không có sentinel hợp lệ).

### 3. Prompt — `app/api/business_chat_prompt.py`

Thêm khối `LEAD_CONTRACT` (song song `SUGGESTION_CONTRACT`, luôn chèn — không phụ thuộc catalogue, vì lead có thể không gắn gói cụ thể):

> Khi khách thể hiện ý định **mua/đặt hàng/ký hợp đồng** rõ ràng (không chỉ hỏi thông tin), trả lời như bình thường rồi kết thúc bằng đúng một dòng:
> `[[LEAD: id1,id2|tóm tắt ngắn gọn nhu cầu, kèm ngân sách nếu khách có nêu]]`
> (để trống trước dấu `|` nếu không có gói cụ thể). Không dùng cùng lúc với dòng gợi ý gói — chỉ chọn một trong hai, hoặc không dòng nào nếu khách chỉ đang hỏi thông tin.

Cập nhật lại đoạn về `[[GOI_Y:...]]` để nêu rõ ranh giới: gợi ý gói dùng khi nhu cầu **còn rộng**; `[[LEAD:...]]` dùng khi ý định **đã rõ, sẵn sàng tiến tới mua/ký**.

### 4. `stream_business_chat` — SSE event `lead_prompt`

Trong `app/services/business_chat.py`, sau khi `RecommendationSentinelFilter` xử lý xong một đoạn `visible`, đưa tiếp qua `LeadSentinelFilter` trước khi yield `delta`. Ở `finish()`, nếu có `LeadDraft`:

- Validate lại `package_ids` với catalog active — **tái dùng thẳng** `resolve_recommendations()` + `to_card()` từ `business_packages.py` (không viết lại logic lọc/cap 3 id).
- Yield SSE event mới: `("lead_prompt", {"summary": draft.summary, "packages": cards})`.
- **Không lưu DB ở bước này** — đây chỉ là bản nháp hiển thị cho khách xác nhận. Nếu khách reload trang trước khi xác nhận, bản nháp mất — chấp nhận được, khách hỏi lại là ra.
- `lead_prompt` không được lưu vào `ChatMessage.recommended_packages` (khác trường, khác vòng đời) — không cần thay schema `ChatMessage`.

### 5. `POST /api/v1/business/leads`

`app/schemas/business.py` thêm:

```python
class BusinessLeadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(..., min_length=1, max_length=1000)
    package_ids: list[int] = Field(default_factory=list)

class BusinessLeadCreated(BaseModel):
    id: int
    created_at: datetime
```

`app/api/business_chat.py` (hoặc file mới `business_leads.py` nếu router hiện tại đã dài — kiểm tra khi viết plan) thêm endpoint, sau `get_current_business_user`:

- Re-validate `package_ids` lại với catalog active (phòng trường hợp catalogue đổi giữa lúc gợi ý và lúc khách bấm xác nhận) — dùng lại `resolve_recommendations`.
- Tạo `BusinessLead` với snapshot `company_name`/`phone`/`email` từ `current_user`.
- `BackgroundTasks.add_task(notify_lead_created, lead.id)` — theo đúng pattern `notify_document_uploaded` (best-effort, không chặn response).
- Trả `BusinessEnvelope[BusinessLeadCreated]`.

### 6. n8n outbound — `notify_lead_created`

Thêm hàm mới trong `app/services/n8n_webhook.py`, cùng pattern với `notify_document_uploaded`: no-op nếu thiếu `N8N_WEBHOOK_URL`, swallow lỗi, timeout 5s.

```json
{
  "event": "lead.created",
  "lead": {
    "id": 1, "company_name": "...", "contact_phone": "...", "contact_email": "...",
    "summary": "...", "packages": [{"id": 3, "name": "..."}],
    "created_at": "2026-09-15T..."
  }
}
```

**Giả định phía n8n (ngoài phạm vi code)**: workflow n8n hiện tại phải thêm một nhánh rẽ theo `event` (`document.uploaded` vs `lead.created`) và định dạng tin nhắn Telegram riêng cho lead — đây là thay đổi cấu hình bên n8n, không phải backend.

`lead.summary` trong payload đến từ chính request body của khách hàng xác nhận (`POST /business/leads`), không chỉ thuần từ output đã validate của model: server không thể phân biệt một summary đến từ đề xuất `[[LEAD:...]]` với một summary do client tự soạn rồi gửi thẳng lên (bản nháp `lead_prompt` không được lưu DB để đối chiếu lại). Vì vậy phía n8n phải coi `lead.summary` là free text chưa tin cậy khi format vào tin nhắn Telegram — tránh dùng parse mode Markdown/HTML có thể bị khai thác, hoặc escape nội dung trước khi chèn vào tin nhắn.

### 7. Frontend

- `businessApi.js`: thêm `businessChatApi.createLead({summary, package_ids})` (POST `/leads`); switch trong `streamBusinessChat` thêm `case 'lead_prompt': onLeadPrompt?.(chunk)`.
- `BusinessChatPage.jsx`: thêm handler `onLeadPrompt` gắn `leadPrompt` vào message cuối, giống cách `recommendations` đang được gắn.
- Component mới `BusinessLeadPrompt.jsx` (song song `BusinessPackageCards.jsx`): hiện tóm tắt + tên gói liên quan (nếu có) + nút "Gửi yêu cầu tới đội Micco" / "Bỏ qua". Bấm gửi → gọi `createLead`, chuyển sang trạng thái đã gửi ("Đội Micco sẽ liên hệ sớm") bằng state cục bộ — không cần refetch history.
- `BusinessMessage.jsx`: render `BusinessLeadPrompt` khi `message.leadPrompt` có giá trị, cạnh chỗ đang render `BusinessPackageCards`.

## Testing

- Unit `LeadSentinelFilter`: sentinel hợp lệ có/không ids, thiếu dấu `|` (hỏng), sentinel bị cắt giữa chừng nhiều chunk, vượt `_MAX_SENTINEL_BODY` (trả về text nguyên văn), ids có ký tự rác.
- Unit endpoint tạo lead: `package_ids` chứa id không active bị loại, cap 3 (tái dùng `resolve_recommendations`, test chỉ cần phủ đường gọi, không lặp lại test của hàm đó).
- Integration `POST /business/leads`: thiếu token → 401; `summary` rỗng → 422; hợp lệ → 200, tạo đúng row với snapshot liên hệ khớp `current_user`, gọi `notify_lead_created` (mock `httpx`).
- Integration `business_chat` stream: LLM trả lời có `[[LEAD: ...]]` → text hiển thị không chứa sentinel, có event `lead_prompt` đúng payload; sentinel hỏng → không có `lead_prompt`, câu trả lời vẫn hiển thị bình thường (fail-closed, giống test hiện có của `recommendations`).
- Frontend: không có test tự động hiện có cho portal — theo `CLAUDE.md`, chạy `/e2e-test` xác nhận luồng xác nhận gửi lead trên trình duyệt thật trước khi coi là xong.

## Config bổ sung

- Không thêm secret/URL mới — tái dùng `N8N_WEBHOOK_URL`, phân nhánh bằng field `event`.
- Migration mới: `012_add_business_leads.py`.
