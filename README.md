# BOT Conversation V2

Dự án độc lập áp dụng kiến trúc:

`Message → Planner → Executor → Presenter → API response`

Source này không import hoặc chỉnh sửa `../BOT`. Nó chỉ dùng chung PostgreSQL khi
hai dự án được cấu hình cùng `DATABASE_URL`.

## Vai trò từng phần

- `app/conversation/planner.py`: nhờ AI chuyển ngôn ngữ tự nhiên thành kế hoạch JSON.
- `app/conversation/executor.py`: chạy nghiệp vụ và chỉ lấy dữ liệu thật từ DB.
- `app/conversation/presenter.py`: nhờ AI diễn đạt kết quả đã xác minh.
- `app/conversation/context.py`: giữ sản phẩm gần nhất và lịch sử theo channel/session.
- `app/conversation/service.py`: điều phối toàn bộ luồng và đo thời gian.
- `app/ai/providers/`: adapter Gemini và OpenAI.
- `app/database/`: truy vấn catalog và knowledge PostgreSQL, không đọc `products.json`.
- `app/knowledge/`: tạo text embedding và tìm các knowledge chunk bằng pgvector.

## Chạy lần đầu

PowerShell:

```powershell
cd "D:\ĐÔNG HẢI\DATA\BOT_Conversation_V2"
Copy-Item .env.example .env
notepad .env
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8010
```

Không dùng port 8000 để tránh xung đột với dự án `BOT` hiện tại.

Mở Swagger:

`http://127.0.0.1:8010/docs`

Mở giao diện chat độc lập:

`http://127.0.0.1:8010/`

Mở giao diện quản trị đồng bộ:

`http://127.0.0.1:8010/admin/products`

Trang admin hỗ trợ nhập SKU, Excel, xem tiến độ job và danh sách sản phẩm phân
trang 20 sản phẩm/trang. Cửa sổ chat trong admin nhúng giao diện V2 và chỉ gọi
`/api/chat` cùng `/api/chat/image`; router admin không chứa endpoint chat cũ.

Request thử:

```json
{
  "message": "Tư vấn cho anh 3 mẫu giày thể thao",
  "session_id": "web-test-001",
  "channel": "web"
}
```

Hỏi tiếp cùng `session_id`:

```json
{
  "message": "Cho anh xem ảnh màu kem",
  "session_id": "web-test-001",
  "channel": "web"
}
```

## Kiểm thử không gọi AI thật

```powershell
python -m unittest discover -s tests -v
```

## Trạng thái tính năng

- Chat text sản phẩm: hoàn thành.
- Hỏi tiếp màu, size, giá, chất liệu, đế, chiều cao: hoàn thành.
- Gợi ý sản phẩm cùng loại: hoàn thành.
- Trả danh sách URL ảnh có cấu trúc cho Web/Telegram: hoàn thành.
- Chuyển Gemini/OpenAI qua `.env`: hoàn thành.
- Nhận diện ảnh sản phẩm: đã chuyển sang V2 với crop, CLIP/pgvector và Gemini verifier.
- RAG policy: đã nối với các bảng `knowledge_documents` và `knowledge_chunks`.
- Giao diện Web: đã nối trực tiếp với `/api/chat`, có session, reset và album ảnh.
- Telegram transport: chưa nối; sau này sẽ gọi chung `ConversationService`.

## Kiểm tra RAG

Đảm bảo `.env` dùng đúng provider/model/dimension đã dùng lúc import knowledge:

```env
RAG_ENABLED=true
RAG_EMBEDDING_PROVIDER=gemini
RAG_EMBEDDING_MODEL=gemini-embedding-001
RAG_EMBEDDING_DIMENSION=768
```

Sau đó gọi `/api/chat` với `Chính sách đổi size như thế nào?`. Response đúng
sẽ có `intent=policy_question`, `status=knowledge_found` và danh sách `sources`.

## Production

`ConversationContextStore` đang giữ dữ liệu trong RAM. Khi chạy nhiều worker hoặc
nhiều máy, thay adapter này bằng Redis. Planner, Executor và Presenter không cần đổi.

## Nhận diện ảnh trên Web

Nhấn nút camera trong giao diện hoặc gọi `POST /api/chat/image` dạng multipart:

- `image`: JPEG, PNG hoặc WebP.
- `session_id`: mã phiên hội thoại.
- `channel`: `web`.
- `caption`: câu hỏi đi kèm, có thể để trống.

Luồng xử lý: Gemini phân loại và tìm vùng sản phẩm → crop → CLIP embedding →
pgvector lấy ứng viên → Gemini xác minh → PostgreSQL lấy thông tin chính thức →
Presenter viết câu trả lời. Mã nhận diện được được lưu vào context để khách có thể
hỏi tiếp về màu, size, chất liệu hoặc yêu cầu ảnh bằng endpoint text.
