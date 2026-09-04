# Đông Hải AI — BOT Conversation V2

Chatbot tư vấn sản phẩm đa kênh cho Đông Hải. Web, Telegram và Facebook dùng chung một lõi hội thoại để tìm sản phẩm, nhận diện ảnh, trả lời tài liệu RAG, lập đơn nháp và chuyển đơn đã xác nhận sang Google Sheets.

> Trạng thái: sẵn sàng cho môi trường staging. Trang quản trị đã có đăng nhập bằng cookie ký số; trước khi chạy production vẫn cần bảo mật secret, giám sát, sao lưu và cơ chế triển khai được nêu ở cuối tài liệu.

Tài liệu kiến trúc và vận hành chi tiết nằm trong [dự án.txt](./dự%20án.txt).

## Chức năng hiện có

- Tư vấn sản phẩm bằng mã, tên, loại, màu, size và nhu cầu tự nhiên.
- Gợi ý sản phẩm cùng loại, gửi ảnh từ CDN Shopify.
- Nhận diện sản phẩm từ ảnh bằng CLIP/pgvector và AI xác minh ứng viên.
- Trả lời chính sách, cửa hàng, size, đổi trả, vận chuyển và khuyến mãi bằng RAG.
- Hội thoại dùng chung cho Web, Telegram và Facebook Messenger.
- Giỏ hàng nhiều sản phẩm, nhiều biến thể; thu thập thông tin nhận hàng.
- Tính tiền sản phẩm, phí vận chuyển và ưu đãi ở mức đơn nháp.
- Ghi đơn đã xác nhận sang Google Sheets để nhân viên kiểm tra.
- Lưu trạng thái hội thoại trong Redis và lịch sử theo dõi trong PostgreSQL.
- Human mode: tạm dừng bot để nhân viên tiếp quản khách trên Telegram/Facebook.
- Trang quản trị sản phẩm, knowledge, prompt và hội thoại.
- Đồng bộ Shopify và tạo image embedding bằng worker riêng.

## Kiến trúc

```text
Web / Telegram / Facebook
            │
            ▼
     Channel Dispatcher
            │
            ▼
 Planner → Executor → Presenter
    │          │          │
    │          ├─ PostgreSQL catalog
    │          ├─ PostgreSQL + pgvector RAG
    │          ├─ Redis conversation/order draft
    │          └─ Google Sheets export
    └─ Gemini hoặc OpenAI

Admin UI → Redis reliable queue → Product sync worker
                                  ├─ Shopify
                                  ├─ local product images
                                  ├─ PostgreSQL catalog
                                  └─ CLIP image embeddings
```

Nguyên tắc dữ liệu:

- PostgreSQL là nguồn dữ liệu sản phẩm dùng khi chatbot trả lời.
- Redis giữ trạng thái hội thoại đang hoạt động, human mode và hàng đợi đồng bộ.
- PostgreSQL giữ lịch sử hội thoại lâu dài để quản trị và đánh giá.
- Ảnh local dùng để tạo embedding và xác minh ảnh; ảnh gửi khách lấy từ CDN Shopify.
- File JSON chỉ còn vai trò snapshot/staging tương thích trong pipeline đồng bộ, không phải catalog runtime của chatbot.
- `manifest.json` không còn được sử dụng; metadata ảnh local được lưu trong bảng `product_images`.

## Yêu cầu

- Python 3.11+
- PostgreSQL có extension `vector` (pgvector)
- Redis 7+
- Docker Desktop được khuyến nghị để chạy Redis trên Windows
- Tài khoản/API key Gemini hoặc OpenAI
- Shopify Admin API nếu dùng đồng bộ sản phẩm
- Google service account nếu dùng xuất đơn Google Sheets

## Cài đặt nhanh trên Windows

### 1. Tạo môi trường Python

```powershell
cd "D:\ĐÔNG HẢI\DATA\BOT_Conversation_V2"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 2. Chạy Redis bằng Docker

```powershell
docker run -d --name donghai-redis -p 6379:6379 redis:7-alpine
docker exec donghai-redis redis-cli ping
```

Kết quả hợp lệ là `PONG`.

### 3. Tạo PostgreSQL và chạy migration

Tạo database, bật pgvector, sau đó chạy theo đúng thứ tự:

```powershell
psql "$env:DATABASE_URL" -f db_postgre/001_product_catalog.sql
psql "$env:DATABASE_URL" -f db_postgre/002_product_image_embeddings.sql
psql "$env:DATABASE_URL" -f db_postgre/003_customer_care_rag.sql
psql "$env:DATABASE_URL" -f db_postgre/004_conversation_history.sql
psql "$env:DATABASE_URL" -f db_postgre/005_admin_users.sql
```

Nếu PowerShell chưa có biến môi trường:

```powershell
$env:DATABASE_URL = "postgresql://postgres:MAT_KHAU@127.0.0.1:5432/donghai_bot"
```

### 4. Tạo file `.env`

Dự án không cung cấp `.env.example`. Tạo `.env` tại thư mục gốc và chỉ bật các tích hợp cần dùng:

```dotenv
# Database và Redis
DATABASE_URL=postgresql://postgres:MAT_KHAU@127.0.0.1:5432/donghai_bot
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_CONVERSATION_ENABLED=true
REDIS_CONVERSATION_TTL_SECONDS=604800
CONVERSATION_HISTORY_LIMIT=12

# AI hội thoại: gemini hoặc openai
AI_PROVIDER=gemini
AI_FALLBACK_PROVIDER=openai
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini

# Kênh được khởi tạo, ngăn cách bằng dấu phẩy
CHANNEL_PROVIDER=web,telegram,facebook

# Telegram — chỉ cần khi bật telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=

# Facebook — chỉ cần khi bật facebook
FACEBOOK_PAGE_ACCESS_TOKEN=
FACEBOOK_VERIFY_TOKEN=
FACEBOOK_APP_SECRET=
FACEBOOK_GRAPH_API_VERSION=v23.0

# Shopify — chỉ cần cho đồng bộ sản phẩm
SHOP=
SHOPIFY_TOKEN=
SHOPIFY_API_VERSION=2025-07

# Image embedding/vector search
PRODUCT_VECTOR_SEARCH_ENABLED=true
IMAGE_EMBEDDING_MODEL=ViT-B-32
IMAGE_EMBEDDING_PRETRAINED=laion2b_s34b_b79k
VECTOR_SEARCH_LIMIT=30
VECTOR_MIN_SIMILARITY=0.35
VECTOR_AUTO_ACCEPT_SIMILARITY=0.96
VECTOR_MIN_MARGIN=0.08
VECTOR_MAX_CANDIDATES=3

# RAG — phải khớp với embedding đã lưu trong DB
RAG_ENABLED=true
RAG_EMBEDDING_PROVIDER=gemini
RAG_EMBEDDING_MODEL=gemini-embedding-001
RAG_EMBEDDING_DIMENSION=768
RAG_TOP_K=5
RAG_MIN_SIMILARITY=0.45

# Google Sheets — tùy chọn
GOOGLE_SHEETS_ENABLED=false
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_ORDERS_RANGE=Orders!A:V
GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-sheets-service-account.json

# Human mode
HUMAN_MODE_ENABLED=true
HUMAN_MODE_TTL_SECONDS=86400

# Đăng nhập trang quản trị
ADMIN_AUTH_ENABLED=true
ADMIN_SESSION_SECRET=THAY_CHUOI_NGAU_NHIEN_IT_NHAT_32_KY_TU
ADMIN_SESSION_TTL_SECONDS=43200
ADMIN_REMEMBER_TTL_SECONDS=2592000
ADMIN_COOKIE_SECURE=false

# Log: mặc định chỉ hiện terminal
LOG_LEVEL=INFO
LOG_TO_FILE=false
LOG_ACCESS_ENABLED=false
LOG_DIR=log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=10
```

Ở mức `INFO`, terminal chỉ giữ log khởi động, thay đổi trạng thái quan trọng,
cảnh báo/lỗi và một dòng `BOT RESPONSE` có thời gian cho mỗi phản hồi. Đặt
`LOG_LEVEL=DEBUG` khi cần xem Planner, Executor, RAG, vector, webhook và lịch sử.
`LOG_ACCESS_ENABLED=true` chỉ dùng khi cần xem toàn bộ request HTTP/Uvicorn.

Không commit `.env`, token, API key hoặc file service account lên Git.

Khi chạy local bằng HTTP, dùng `ADMIN_COOKIE_SECURE=false`. Khi production đã có HTTPS, phải đổi thành `ADMIN_COOKIE_SECURE=true`. Có thể tạo session secret ngẫu nhiên trong PowerShell bằng:

```powershell
[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLower()
```

Tài khoản và mật khẩu quản trị được lưu trong PostgreSQL, không đặt trong `.env`. Sau khi chạy migration `005_admin_users.sql`, tạo tài khoản đầu tiên bằng lệnh dưới đây; chương trình sẽ yêu cầu nhập mật khẩu hai lần và chỉ lưu password hash:

```powershell
python -m app.scripts.create_admin_user --username admin --display-name "Quản trị viên"
```

Đổi mật khẩu và thu hồi toàn bộ phiên cũ của tài khoản:

```powershell
python -m app.scripts.create_admin_user --username admin --update-password
```

### 5. Chạy ứng dụng và worker

Cách nhanh trên Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

Script mở worker ở một tiến trình riêng và chạy FastAPI tại port `8000`.

Hoặc chạy thủ công bằng hai terminal:

```powershell
# Terminal 1 — web/API/chatbot
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# Terminal 2 — đồng bộ Shopify và embedding
python -m app.workers.product_sync_worker
```

Worker đứng yên khi hàng đợi trống là trạng thái bình thường.

## Địa chỉ sử dụng

- Trang sản phẩm: <http://127.0.0.1:8000/admin/products>
- Đăng nhập quản trị: <http://127.0.0.1:8000/admin/login>
- Knowledge: <http://127.0.0.1:8000/admin/knowledge>
- Prompt: <http://127.0.0.1:8000/admin/prompts>
- Hội thoại/Human mode: <http://127.0.0.1:8000/admin/conversations>
- Tài khoản quản trị: <http://127.0.0.1:8000/admin/users>
- Biến môi trường (chỉ admin): <http://127.0.0.1:8000/admin/environment>
- Swagger API: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>

Trang biến môi trường chỉ cho role `admin`. Secret được ẩn mặc định nhưng có thể
Hiện/Ẩn để kiểm tra. Nút lưu ghi file `.env` và kích hoạt Uvicorn reload để nạp
lại cấu hình khi chạy local bằng `start.ps1`; thay đổi session secret sẽ yêu cầu
đăng nhập lại. Khi triển khai bằng service production, phải cập nhật file môi
trường production và khởi động lại cả app lẫn product sync worker.

## API chatbot

Tin nhắn văn bản:

```powershell
$body = @{
    message = "Tư vấn cho tôi 3 mẫu giày thể thao size 42"
    session_id = "web-test-001"
    channel = "web"
    history = @()
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/chat" `
  -ContentType "application/json" `
  -Body $body
```

Xóa trạng thái hội thoại đang hoạt động:

```powershell
$body = @{ session_id = "web-test-001"; channel = "web" } |
    ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/chat/reset" `
  -ContentType "application/json" `
  -Body $body
```

Reset chỉ xóa cache/trạng thái Redis; lịch sử PostgreSQL vẫn được giữ để theo dõi.

## Đồng bộ sản phẩm

1. Mở `/admin/products`.
2. Nhập SKU trực tiếp, tải Excel hoặc chọn đồng bộ tất cả.
3. API tạo job trong Redis và giao diện theo dõi tiến độ.
4. Worker lấy dữ liệu Shopify, tải ảnh, upsert catalog PostgreSQL và tạo embedding cho ảnh chưa có vector.
5. Bảng sản phẩm hiển thị số variant, ảnh local, embedding và trạng thái AI.

Giới hạn nhập danh sách trực tiếp/Excel là 1.000 SKU mỗi lần. Đồng bộ tất cả là một tác vụ quản trị riêng và có xác nhận trước khi chạy.

## Knowledge và prompt

- Trang Knowledge nhận TXT, Markdown và PDF có lớp văn bản.
- Khi đổi provider/model/dimension của RAG, phải import hoặc tạo embedding lại tài liệu.
- `003_customer_care_rag.sql` hiện dùng vector 768 chiều; đổi dimension cần migration schema tương ứng.
- `prompts/instruction.txt` là prompt nghiệp vụ duy nhất: vai trò, cách tư vấn,
  flow bán hàng và format phản hồi. Người quản trị không cần biết tên intent/tool.
- Hợp đồng kỹ thuật Planner/Presenter nằm trong `app/ai/internal_prompts/`, không
  hiển thị trên trang Prompt và chỉ thay đổi khi code/schema thay đổi.
- `prompts/promotion_rules.txt` là dữ liệu chương trình khuyến mãi, không chứa
  hướng dẫn trường kỹ thuật.
- Các prompt ảnh, CTA và phản hồi nhanh được quản lý tại `/admin/prompts`.
- Hệ thống lưu phiên bản cũ trong `prompts/.versions` trước khi ghi đè.
- Một số cấu hình tải lúc startup, vì vậy nên khởi động lại app sau khi sửa prompt nếu thay đổi chưa áp dụng ngay.

## Kết nối channel

### Web

Luôn dùng được qua `/api/chat`, `/api/chat/image` và bong bóng chat trong trang quản trị.

### Telegram

Webhook:

```text
https://TEN-MIEN-CUA-BAN/api/telegram/webhook
```

Xem hướng dẫn đăng ký chi tiết trong [TELEGRAM_SETUP.md](./TELEGRAM_SETUP.md).

### Facebook Messenger

Callback URL:

```text
https://TEN-MIEN-CUA-BAN/webhook/facebook
```

`FACEBOOK_VERIFY_TOKEN` dùng cho bước verify webhook; `FACEBOOK_APP_SECRET` dùng xác minh chữ ký POST. Staff trả lời khách trong Meta Business Suite sẽ kích hoạt Human mode cho khách đó; bot chỉ hoạt động lại khi hết thời gian hoặc được bật lại trong trang Hội thoại.

## Kiểm thử

```powershell
python -m compileall -q app
python -m unittest discover -s tests -v
```

Trạng thái gần nhất ngày 28/08/2026: `147` test đã chạy thành công.

## Lưu ý khi triển khai production

- Chạy FastAPI và product sync worker thành hai service/process độc lập; người vận hành không cần mở hai terminal nếu dùng Docker Compose, Windows Service hoặc process manager.
- Dùng PostgreSQL/Redis managed hoặc có persistence, password, backup và giám sát.
- Dùng HTTPS; đặt secret trong secret manager, không đặt trong source hoặc image Docker.
- Gắn volume dùng chung cho `data/product_images` nếu web và worker chạy ở máy/container khác nhau.
- Chạy migration `005_admin_users.sql`, tạo ít nhất một user quản trị, bật `ADMIN_AUTH_ENABLED=true`, đặt session secret riêng và `ADMIN_COOKIE_SECURE=true` trước khi public. User được lưu trong PostgreSQL; chỉ role `admin` được quản lý tài khoản. Các trang nghiệp vụ còn lại chưa giới hạn riêng giữa `manager` và `staff`.
- Thêm rate limit, request size limit, timeout, retry có kiểm soát và cảnh báo lỗi AI/API.
- Hiện hàng đợi sự kiện Facebook theo người dùng nằm trong bộ nhớ process; để scale nhiều web worker/replica cần chuyển phần này sang Redis hoặc bảo đảm sticky routing. Trước khi làm việc đó nên chạy một web worker.
- Job upload Knowledge hiện dùng background task trong FastAPI; production nên tách sang worker bền vững.
- Google Sheets là kênh bàn giao đơn cho nhân viên, không nên là hệ thống quản trị đơn hàng duy nhất.
- Logic khuyến mãi hiện là kết quả AI/đơn nháp và vẫn cần nhân viên kiểm tra trước khi tạo đơn chính thức.

## Cấu trúc quan trọng

```text
app/
  ai/                    Gemini/OpenAI adapters
  channels/              Web/Telegram/Facebook providers
  conversation/          Planner, Executor, Presenter, order flow
  database/              PostgreSQL repositories
  knowledge/             RAG embedding và retrieval
  product_recognition/   CLIP, vector search, AI verification
  ai/internal_prompts/   Hợp đồng kỹ thuật Planner/Presenter, không chỉnh nghiệp vụ
  routes/                 API và trang quản trị
  services/               Shopify, Sheets, Redis queue, history
  workers/                Product sync worker
  static/                 CSS, JS, logo
  templates/              Giao diện admin
db_postgre/               4 migration SQL
data/product_images/      Ảnh catalog local
knowledge/                Tài liệu nguồn RAG
prompts/                  Instruction nghiệp vụ và cấu hình nội dung có thể quản trị
tests/                    Unit/integration-style tests
```

## Xử lý lỗi nhanh

- Worker không in thêm log: hàng đợi Redis đang trống, đây không phải lỗi.
- Giao diện đồng bộ polling mãi: kiểm tra worker, Redis và key job trong Redis.
- RAG không tìm thấy sau khi đổi AI provider: embedding query không khớp provider/model/dimension của tài liệu đã index; cần re-embed.
- Ảnh không nhận diện: kiểm tra `product_images.local_path`, file local và `product_image_embeddings`.
- Ảnh gửi khách 404: kiểm tra `source_url` CDN Shopify trong DB; chatbot không dùng local path làm URL gửi khách.
- Google Sheets lỗi 429/503: service có retry, nhưng vẫn cần kiểm tra quota, quyền chia sẻ sheet và service account.
- Telegram/Facebook webhook nhận 200 nhưng bot không trả lời: kiểm tra token, channel trong `CHANNEL_PROVIDER`, Human mode và log `CHANNEL RESPONSE`.
