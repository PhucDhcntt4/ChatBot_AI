# Hướng dẫn cấu hình và chạy Bot Conversation V2 trên production

Tài liệu này áp dụng cho cấu trúc hiện tại của `BOT_Conversation_V2`:

- Bot và trang quản trị chạy chung trong `app.main:app`.
- PostgreSQL lưu tài khoản và lịch sử hội thoại.
- Redis lưu ngữ cảnh hội thoại và trạng thái nhân viên tiếp quản.
- Qdrant lưu catalog sản phẩm và vector ảnh.
- RAG Service là một service riêng, bot chỉ gọi qua HTTP API.

## 1. Cấu trúc thư mục production

```text
BOT_Conversation_V2/
├── app/
├── prompts/
├── data/
│   └── product_images/
├── log/
├── secrets/
│   └── google-sheets-service-account.json  # chỉ khi dùng Google Sheets
├── .env
├── requirements.txt
└── int_db.py
```

Ý nghĩa:

- `app/`: source code backend, bot, webhook và giao diện quản trị.
- `prompts/`: prompt nghiệp vụ, CTA và nhận diện sản phẩm.
- `data/product_images/`: ảnh marketing nhận diện tải lên từ trang sản phẩm.
- `log/`: log xoay vòng nếu bật `LOG_TO_FILE=true`.
- `secrets/`: credential Google Sheets; không đưa lên Git.
- `.env`: toàn bộ cấu hình và khóa bí mật production.
- `int_db.py`: tạo ba bảng PostgreSQL và tài khoản quản trị.

Không cần đưa lên production: `.git/`, `tests/`, `backups/`,
`data/backups/`, `.vscode/`, `__pycache__/`, `.pytest_cache/` và log cũ.

## 2. Dịch vụ cần chạy

Theo cách bố trí hiện tại:

| Dịch vụ | Địa chỉ đề nghị | Công dụng |
|---|---|---|
| RAG Service | `http://127.0.0.1:8000` | Tra cứu tài liệu CSKH |
| Bot Conversation | `http://127.0.0.1:8001` | Bot, webhook và trang admin |
| Qdrant | `http://127.0.0.1:6333` | Catalog và vector ảnh |
| PostgreSQL | `127.0.0.1:5432` | User và lịch sử hội thoại |
| Redis | `127.0.0.1:6379` | Cache và human mode |

Không chạy RAG Service và Bot Conversation cùng một cổng.

## 3. Chuẩn bị Python

Khuyến nghị Python 3.11 và virtual environment riêng.

### Windows PowerShell

```powershell
cd "D:\DUONG_DAN\BOT_Conversation_V2"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Nếu PowerShell chặn activate script:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

### Linux

```bash
cd /opt/donghai-bot
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`torch`, `torchvision` và `open-clip-torch` có dung lượng lớn. Nếu máy dùng
GPU, cài đúng bản PyTorch dành cho CUDA của máy trước khi cài các thư viện còn
lại.

## 4. Tạo thư mục có quyền ghi

### Windows PowerShell

```powershell
New-Item -ItemType Directory -Force data\product_images | Out-Null
New-Item -ItemType Directory -Force log | Out-Null
New-Item -ItemType Directory -Force secrets | Out-Null
```

### Linux

```bash
mkdir -p data/product_images log secrets
sudo chown -R donghai:donghai data log secrets
chmod 750 data data/product_images log secrets
```

Nếu chạy bằng Docker, `data/product_images` và `log` nên được gắn volume để
không mất dữ liệu khi tạo lại container.

## 5. Cấu hình `.env`

Không chép nguyên khóa bí mật từ môi trường development sang tài liệu hoặc Git.
Tạo `.env` trên server và điền các giá trị thật.

### 5.1 Kênh hoạt động

```env
CHANNEL_PROVIDER=web,telegram,facebook
```

- Chỉ web: `CHANNEL_PROVIDER=web`
- Web và Facebook: `CHANNEL_PROVIDER=web,facebook`
- Bật Telegram thì phải có token và webhook secret.
- Bật Facebook thì phải có Page Access Token, Verify Token và App Secret.

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=

FACEBOOK_PAGE_ACCESS_TOKEN=
FACEBOOK_APP_SECRET=
FACEBOOK_VERIFY_TOKEN=
FACEBOOK_GRAPH_API_VERSION=v23.0
```

### 5.2 AI provider

Ví dụ dùng Gemini chính và OpenAI dự phòng:

```env
AI_PROVIDER=gemini
AI_FALLBACK_PROVIDER=openai

GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite

OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
```

Nếu không dùng provider dự phòng:

```env
AI_FALLBACK_PROVIDER=
```

### 5.3 PostgreSQL

```env
DATABASE_URL=postgresql://donghai:MAT_KHAU@127.0.0.1:5432/donghai_bot
```

Tạo database và user trước khi chạy `int_db.py`. Không dùng tài khoản superuser
cho ứng dụng nếu không cần thiết.

### 5.4 Redis

```env
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_SOCKET_TIMEOUT_SECONDS=15
REDIS_CONVERSATION_ENABLED=true
REDIS_CONVERSATION_PREFIX=donghai:conversation
REDIS_CONVERSATION_TTL_SECONDS=604800
```

- `604800` giây tương đương 7 ngày.
- Nếu Redis có mật khẩu:

```env
REDIS_URL=redis://:MAT_KHAU@127.0.0.1:6379/0
```

### 5.5 Qdrant catalog và vector ảnh

```env
PRODUCT_CATALOG_PROVIDER=qdrant
IMAGE_QDRANT_URL=http://127.0.0.1:6333
IMAGE_QDRANT_API_KEY=
QDRANT_CATALOG_COLLECTION=bot_product_catalog_v1
IMAGE_QDRANT_COLLECTION=bot_product_images_clip_v2
```

Collection catalog phải tồn tại và chứa sản phẩm trước khi bot khởi động.
Collection ảnh dùng vector CLIP 512 chiều, khoảng cách Cosine.

```env
PRODUCT_VECTOR_SEARCH_ENABLED=true
IMAGE_EMBEDDING_MODEL=ViT-B-32
IMAGE_EMBEDDING_PRETRAINED=laion2b_s34b_b79k
VECTOR_SEARCH_LIMIT=30
VECTOR_MIN_SIMILARITY=0.35
VECTOR_AUTO_ACCEPT_SIMILARITY=0.96
VECTOR_MIN_MARGIN=0.08
VECTOR_MAX_CANDIDATES=3
VECTOR_REFERENCES_PER_PRODUCT=2
```

Không đổi model hoặc pretrained sau khi đã tạo vector, trừ khi rebuild toàn bộ
collection ảnh.

### 5.6 RAG Service

```env
RAG_ENABLED=true
RAG_SERVICE_URL=http://127.0.0.1:8000
RAG_SERVICE_API_KEY=
RAG_SERVICE_ADMIN_API_KEY=
RAG_SERVICE_TIMEOUT_SECONDS=40
RAG_SERVICE_ADMIN_TIMEOUT_SECONDS=180
```

Phạm vi tài liệu CSKH:

```env
RAG_SEARCH_DOC_TYPE_ID=1
RAG_SEARCH_GROUP_IDS=
```

- `RAG_SEARCH_GROUP_IDS=` để trống: tìm mọi nhóm thuộc loại tài liệu đã chọn.
- Giới hạn nhiều nhóm: `RAG_SEARCH_GROUP_IDS=3,4,5`.

Chính sách giao hàng:

```env
SHIPPING_POLICY_CATEGORY=shipping
SHIPPING_POLICY_CACHE_SECONDS=300
```

### 5.7 Google Sheets

Nếu không dùng:

```env
GOOGLE_SHEETS_ENABLED=false
```

Nếu dùng:

```env
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_ORDERS_RANGE=Orders!A:V
GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-sheets-service-account.json
```

Phải chia sẻ Google Sheet cho email `client_email` trong service account.

### 5.8 Human mode

```env
HUMAN_MODE_ENABLED=true
HUMAN_MODE_TTL_SECONDS=600
```

`600` giây tương đương 10 phút. Trạng thái human mode được lưu trong Redis.

### 5.9 Đăng nhập quản trị

```env
ADMIN_AUTH_ENABLED=true
ADMIN_SESSION_SECRET=CHUOI_NGAU_NHIEN_TOI_THIEU_32_KY_TU
ADMIN_SESSION_TTL_SECONDS=43200
ADMIN_REMEMBER_TTL_SECONDS=2592000
ADMIN_COOKIE_SECURE=true
```

Tạo secret mới:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

- Production có HTTPS: `ADMIN_COOKIE_SECURE=true`.
- Local chạy HTTP: `ADMIN_COOKIE_SECURE=false`.
- Mọi instance của cùng hệ thống phải dùng cùng `ADMIN_SESSION_SECRET`.
- Không đổi secret tùy ý vì tất cả phiên đăng nhập hiện tại sẽ hết hiệu lực.

### 5.10 Log

```env
LOG_LEVEL=INFO
LOG_TO_FILE=true
LOG_ACCESS_ENABLED=false
LOG_DIR=log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=10
```

- `LOG_ACCESS_ENABLED=false` ẩn các access log lặp lại.
- Mỗi file log tối đa khoảng 10 MB.
- Hệ thống giữ tối đa 10 bản log cũ cho mỗi loại file.
- Nếu dùng Docker/Kubernetes, có thể đặt `LOG_TO_FILE=false` và thu log từ
  stdout/stderr.

### 5.11 Shopify — chỉ cần cho lệnh import sản phẩm

```env
SHOP=ten-shop.myshopify.com
SHOPIFY_TOKEN=
SHOPIFY_API_VERSION=2026-07
```

Các biến này không cần cho việc chatbot chỉ đọc catalog đã có trong Qdrant.

## 6. Khởi tạo PostgreSQL và tài khoản

Chạy một lần trên database mới:

```powershell
python int_db.py --username admin --display-name "Quản trị viên" --role admin
```

Script sẽ yêu cầu nhập mật khẩu hai lần và tạo:

```text
conversation_sessions
conversation_messages
admin_users
```

Script không kết nối Qdrant, Redis hoặc RAG Service. Có thể chạy lại an toàn;
các bảng và tài khoản đang có không bị xóa.

Đặt lại mật khẩu tài khoản đã tồn tại:

```powershell
python int_db.py --username admin --update-password
```

## 7. Kiểm tra dịch vụ phụ thuộc

Redis:

```powershell
redis-cli -u redis://127.0.0.1:6379/0 ping
```

Kết quả đúng:

```text
PONG
```

Qdrant:

```powershell
Invoke-RestMethod http://127.0.0.1:6333/collections
```

Phải nhìn thấy:

```text
bot_product_catalog_v1
bot_product_images_clip_v2
```

RAG Service:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Nếu RAG Service dùng health endpoint khác, thay URL theo service đó.

## 8. Chạy Bot Conversation

### Development trên Windows

```powershell
python -m uvicorn app.main:app --reload --reload-include ".env" --host 127.0.0.1 --port 8001
```

- `--reload`: tự khởi động lại khi code thay đổi; chỉ dùng development.
- `--reload-include ".env"`: theo dõi thay đổi file `.env`.
- `--host 127.0.0.1`: chỉ truy cập từ máy local.
- `--port 8001`: không trùng RAG Service đang chạy cổng 8000.

### Production

```bash
.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8001 \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips=127.0.0.1
```

Giải thích:

- Không dùng `--reload` trên production.
- Dùng `--workers 1` vì ứng dụng có cache trong tiến trình và xử lý webhook.
- Nginx nhận HTTPS công khai rồi proxy về `127.0.0.1:8001`.
- Nếu cần nhiều worker, phải kiểm tra lại toàn bộ trạng thái dùng RAM và chống
  xử lý trùng webhook trước.

## 9. Kiểm tra sau khi chạy

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
```

Trang quản trị:

```text
http://127.0.0.1:8001/admin/products
```

Kiểm tra lần lượt:

1. Đăng nhập trang quản trị.
2. Mở trang Sản phẩm và xem được catalog Qdrant.
3. Mở trang Knowledge và nhận được dữ liệu từ RAG Service.
4. Gửi một tin nhắn web chat.
5. Kiểm tra Redis có context hội thoại.
6. Kiểm tra PostgreSQL có session và message.
7. Nếu bật Sheets, xác nhận đơn thử và kiểm tra dòng mới trong Sheet.

## 10. Webhook production

Facebook webhook:

```text
https://TEN_MIEN/webhook/facebook
```

Telegram webhook:

```text
https://TEN_MIEN/api/telegram/webhook
```

Tên miền phải có HTTPS hợp lệ. Reverse proxy chuyển các request này về Bot
Conversation tại cổng 8001.

## 11. Dừng và khởi động lại

Nếu chạy trực tiếp trong terminal, nhấn:

```text
Ctrl + C
```

Sau khi thay đổi `.env` trên production, phải khởi động lại tiến trình Uvicorn.
Việc lưu `.env` không tự thay đổi các giá trị đã được nạp trong tiến trình đang
chạy.

## 12. Sao lưu

Cần sao lưu đồng thời:

- PostgreSQL.
- Hai collection Qdrant của bot.
- `data/product_images/` nếu có thêm ảnh marketing nhận diện.
- `.env` và `secrets/` vào nơi bảo mật.

Không cần sao lưu Redis nếu chấp nhận mất cache hội thoại và trạng thái human
mode khi Redis bị khởi tạo lại. Lịch sử hội thoại chính vẫn nằm trong
PostgreSQL.

