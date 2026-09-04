# Hướng dẫn triển khai production — Đông Hải AI Conversation V2

Tài liệu này hướng dẫn triển khai source hiện tại lên một máy chủ Ubuntu dùng:

- Nginx và HTTPS làm cổng truy cập công khai.
- FastAPI/Uvicorn phục vụ Web, Telegram và Facebook webhook.
- Một product sync worker độc lập để đồng bộ Shopify, tải ảnh và tạo image embedding.
- PostgreSQL có extension `pgvector` làm nguồn dữ liệu sản phẩm, RAG và lịch sử hội thoại.
- Redis lưu context hội thoại, Human mode và hàng đợi đồng bộ.
- Gemini hoặc OpenAI làm AI provider.
- Google Sheets nhận đơn đã xác nhận nếu tính năng này được bật.

> `start.ps1` và tùy chọn `--reload` chỉ dành cho máy phát triển Windows. Production dùng hai service systemd nên không cần mở hai cửa sổ terminal.

## 1. Kiến trúc triển khai

```text
Khách hàng / Telegram / Facebook
                │ HTTPS :443
                ▼
              Nginx
                │ 127.0.0.1:8000
                ▼
       donghai-bot.service
        FastAPI + Conversation V2
           │              │
           │              ├── Gemini/OpenAI
           │              ├── Shopify CDN
           │              └── Google Sheets
           │
           ├── PostgreSQL + pgvector
           └── Redis
                ▲
                │
      donghai-worker.service
    Shopify sync + local images + CLIP
```

Source hiện tại nên chạy **một Uvicorn worker**. Hàng đợi sự kiện Facebook, chống trùng webhook và một phần xử lý background đang nằm trong bộ nhớ của process. Chỉ tăng số web worker/replica sau khi chuyển các phần này sang Redis hoặc một message broker bền vững.

## 2. Điều kiện trước khi triển khai

Chuẩn bị:

- Một VPS Ubuntu LTS, tối thiểu khoảng 4 CPU, 8 GB RAM và đủ dung lượng lưu ảnh/model.
- Một tên miền, ví dụ `bot.example.com`, đã trỏ bản ghi A/AAAA về VPS.
- Python 3.11 trở lên.
- PostgreSQL và pgvector, hoặc PostgreSQL managed có hỗ trợ extension `vector`.
- Redis 7 trở lên, hoặc Redis managed.
- API key Gemini hoặc OpenAI.
- Shopify Admin API credentials nếu cần đồng bộ sản phẩm.
- Telegram/Facebook credentials nếu bật các channel đó.
- Google service account nếu xuất đơn sang Google Sheets.

Các cổng công khai cần mở:

- `22/tcp`: SSH, nên giới hạn theo IP quản trị.
- `80/tcp`: dùng để cấp/chuyển hướng chứng chỉ HTTPS.
- `443/tcp`: Web, API và webhook.

Không mở `5432`, `6379` hoặc `8000` ra Internet nếu PostgreSQL, Redis và FastAPI chạy cùng máy.

## 3. Chuẩn bị user và source

Đăng nhập VPS bằng tài khoản có quyền `sudo`, sau đó tạo user chạy dịch vụ:

```bash
sudo adduser --system --group --home /opt/donghai-bot donghai
sudo mkdir -p /opt/donghai-bot
sudo chown -R donghai:donghai /opt/donghai-bot
```

Đưa source vào `/opt/donghai-bot`. Khuyến nghị dùng Git:

```bash
sudo -u donghai git clone <GIT_REPOSITORY_URL> /opt/donghai-bot
cd /opt/donghai-bot
```

Nếu copy source thủ công, không chuyển các dữ liệu máy phát triển sau:

- `.venv/`
- `.git/` nếu server không quản lý source bằng Git
- `.env`
- `secrets/`
- `log/`
- file cache Python như `__pycache__/`

Các thư mục sau cần được giữ lại khi cập nhật phiên bản vì có dữ liệu vận hành:

- `data/product_images/`
- `knowledge/`
- `prompts/` nếu nhân viên sửa prompt trên giao diện
- `secrets/` nếu file service account được đặt trong project

Về lâu dài nên chuyển các thư mục dữ liệu này sang `/var/lib/donghai-bot` và gắn volume/symlink để việc thay release không ghi đè dữ liệu.

## 4. Cài thư viện hệ thống và Python

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-dev \
  build-essential git curl ca-certificates \
  nginx postgresql-client
```

Tạo virtual environment và cài dependency:

```bash
cd /opt/donghai-bot
sudo -u donghai python3 -m venv .venv
sudo -u donghai .venv/bin/python -m pip install --upgrade pip
sudo -u donghai .venv/bin/python -m pip install -r requirements.txt
```

`torch`, `torchvision` và `open-clip-torch` có dung lượng lớn. Nếu máy production dùng GPU, cần cài bản PyTorch tương ứng với CUDA của máy thay vì mặc định CPU. Không đổi model image embedding sau khi đã index dữ liệu nếu chưa rebuild toàn bộ embedding.

## 5. Cấu hình PostgreSQL và pgvector

### 5.1. Dùng PostgreSQL cùng VPS

Cài PostgreSQL và gói pgvector phù hợp với phiên bản PostgreSQL của máy. Tên gói pgvector thường có dạng `postgresql-<VERSION>-pgvector`.

Tạo user và database:

```bash
sudo -u postgres psql
```

Trong `psql`:

```sql
CREATE USER donghai_bot WITH PASSWORD 'THAY_MAT_KHAU_MANH';
CREATE DATABASE donghai_bot OWNER donghai_bot;
\c donghai_bot
CREATE EXTENSION IF NOT EXISTS vector;
\q
```

Nếu password có ký tự đặc biệt như `@`, `:`, `/`, `?` hoặc `#`, phải URL-encode khi đưa vào `DATABASE_URL`.

### 5.2. Chạy migration

Chạy đúng thứ tự năm file SQL:

```bash
cd /opt/donghai-bot
export DATABASE_URL='postgresql://donghai_bot:MAT_KHAU_DA_URL_ENCODE@127.0.0.1:5432/donghai_bot'

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/001_product_catalog.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/002_product_image_embeddings.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/003_customer_care_rag.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/004_conversation_history.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/005_admin_users.sql
```

Ý nghĩa:

1. `001_product_catalog.sql`: catalog, variants, màu, ảnh và metadata đồng bộ.
2. `002_product_image_embeddings.sql`: vector ảnh CLIP 512 chiều.
3. `003_customer_care_rag.sql`: tài liệu/chunk RAG 768 chiều.
4. `004_conversation_history.sql`: session và lịch sử tin nhắn lâu dài.
5. `005_admin_users.sql`: tài khoản, password hash, trạng thái và role quản trị.

Kiểm tra:

```bash
psql "$DATABASE_URL" -c "SELECT extname FROM pg_extension WHERE extname='vector';"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM products;"
```

## 6. Cấu hình Redis

Có thể dùng Redis managed hoặc Redis cùng VPS. Nếu cài local:

```bash
sudo apt install -y redis-server
sudo systemctl enable --now redis-server
redis-cli ping
```

Kết quả đúng là:

```text
PONG
```

Production nên:

- Chỉ bind Redis vào mạng private/localhost.
- Đặt password hoặc ACL.
- Bật persistence AOF/RDB nếu cần giữ context và job qua sự cố máy.
- Dùng `rediss://` khi kết nối Redis managed qua TLS.

Redis trong dự án dùng cho ba nhóm dữ liệu:

- `donghai:conversation:*`: trạng thái hội thoại và đơn nháp.
- Human mode: tạm dừng bot khi nhân viên tiếp quản.
- Product sync queue/job: giao việc giữa FastAPI và worker.

## 7. Tạo file biến môi trường production

Không lưu secret trong Git. Tạo `/etc/donghai-bot.env`:

> Trang `/admin/environment` mặc định chỉnh file `.env` trong thư mục dự án và
> phù hợp cho môi trường local chạy bằng `start.ps1`. Production trong hướng dẫn
> này dùng `/etc/donghai-bot.env`; hãy cập nhật file đó bằng quyền hệ thống rồi
> khởi động lại cả `donghai-bot` và `donghai-product-worker`.

```bash
sudo install -m 600 -o root -g root /dev/null /etc/donghai-bot.env
sudo nano /etc/donghai-bot.env
```

Mẫu cấu hình:

```dotenv
# PostgreSQL và Redis
DATABASE_URL=postgresql://donghai_bot:MAT_KHAU_URL_ENCODE@127.0.0.1:5432/donghai_bot
REDIS_URL=redis://:MAT_KHAU_REDIS@127.0.0.1:6379/0
REDIS_SOCKET_TIMEOUT_SECONDS=15

# Context hội thoại
REDIS_CONVERSATION_ENABLED=true
REDIS_CONVERSATION_PREFIX=donghai:conversation
REDIS_CONVERSATION_TTL_SECONDS=604800
CONVERSATION_HISTORY_LIMIT=12

# Đăng nhập trang quản trị
ADMIN_AUTH_ENABLED=true
ADMIN_SESSION_SECRET=THAY_CHUOI_NGAU_NHIEN_IT_NHAT_32_KY_TU
ADMIN_SESSION_TTL_SECONDS=43200
ADMIN_REMEMBER_TTL_SECONDS=2592000
ADMIN_COOKIE_SECURE=true

# AI hội thoại: gemini hoặc openai
AI_PROVIDER=gemini
GEMINI_API_KEY=THAY_API_KEY
GEMINI_MODEL=THAY_MODEL_DA_KIEM_THU
OPENAI_API_KEY=
OPENAI_MODEL=

# Bật các channel cần dùng, phân cách bằng dấu phẩy
CHANNEL_PROVIDER=web,telegram,facebook

# Telegram
TELEGRAM_BOT_TOKEN=THAY_TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET=THAY_CHUOI_BI_MAT_DAI_NGAU_NHIEN

# Facebook Messenger
FACEBOOK_PAGE_ACCESS_TOKEN=THAY_PAGE_ACCESS_TOKEN
FACEBOOK_VERIFY_TOKEN=THAY_VERIFY_TOKEN
FACEBOOK_APP_SECRET=THAY_FACEBOOK_APP_SECRET
FACEBOOK_GRAPH_API_VERSION=THAY_VERSION_DA_KIEM_THU

# Shopify
SHOP=THAY_TEN_SHOP
SHOPIFY_TOKEN=THAY_SHOPIFY_ADMIN_TOKEN
SHOPIFY_API_VERSION=THAY_VERSION_DA_KIEM_THU

# Nhận diện ảnh sản phẩm
PRODUCT_VECTOR_SEARCH_ENABLED=true
IMAGE_EMBEDDING_MODEL=ViT-B-32
IMAGE_EMBEDDING_PRETRAINED=laion2b_s34b_b79k
VECTOR_SEARCH_LIMIT=30
VECTOR_MIN_SIMILARITY=0.35
VECTOR_AUTO_ACCEPT_SIMILARITY=0.96
VECTOR_MIN_MARGIN=0.08
VECTOR_MAX_CANDIDATES=3
VECTOR_REFERENCES_PER_PRODUCT=2
PRODUCT_ALBUM_IMAGE_LIMIT=4

# RAG. Provider/model/dimension phải khớp dữ liệu đã index
RAG_ENABLED=true
RAG_EMBEDDING_PROVIDER=gemini
RAG_EMBEDDING_MODEL=gemini-embedding-001
RAG_EMBEDDING_DIMENSION=768
RAG_TOP_K=5
RAG_MIN_SIMILARITY=0.45
RAG_MAX_CONTEXT_CHARS=6000
RAG_CHUNK_SIZE=1200
RAG_CHUNK_OVERLAP=180

# Gợi ý sản phẩm
PRODUCT_RECOMMENDATION_DEFAULT_COUNT=3
PRODUCT_RECOMMENDATION_MAX_COUNT=5

# Human mode
HUMAN_MODE_ENABLED=true
HUMAN_MODE_TTL_SECONDS=86400

# Google Sheets, có thể tắt cho lần chạy đầu
GOOGLE_SHEETS_ENABLED=false
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_SHEETS_ORDERS_RANGE=Orders!A:V
GOOGLE_SERVICE_ACCOUNT_FILE=/opt/donghai-bot/secrets/google-sheets-service-account.json

# Log production: ưu tiên journalctl, không ghi file trùng lặp
LOG_LEVEL=INFO
LOG_TO_FILE=false
LOG_ACCESS_ENABLED=false

# Redis reliable sync queue, có thể giữ mặc định
REDIS_SYNC_QUEUE=donghai:sync:queue
REDIS_SYNC_PROCESSING=donghai:sync:processing
REDIS_SYNC_JOB_PREFIX=donghai:sync:job
REDIS_SYNC_CANCEL_PREFIX=donghai:sync:cancel
REDIS_SYNC_JOB_TTL_SECONDS=86400
REDIS_SYNC_BLOCK_SECONDS=5
REDIS_SYNC_STALE_SECONDS=1800
REDIS_SYNC_MAX_ATTEMPTS=3
```

Lưu ý cấu hình:

- Nếu chỉ dùng Web, đặt `CHANNEL_PROVIDER=web` và có thể bỏ token Telegram/Facebook.
- Khi có `telegram` trong `CHANNEL_PROVIDER`, bắt buộc có bot token và webhook secret hợp lệ.
- Khi có `facebook`, phải cấu hình page access token, verify token và app secret.
- `RAG_EMBEDDING_PROVIDER` độc lập với `AI_PROVIDER`. Không tự đổi provider/model RAG khi database vẫn chứa embedding cũ.
- `RAG_EMBEDDING_DIMENSION` hiện bắt buộc bằng `768` để khớp migration 003.
- Image embedding hiện là `512` chiều. Đổi model/pretrained cần tạo lại image embedding.
- Để lần khởi động đầu dễ kiểm tra, có thể tạm đặt `RAG_ENABLED=false`, `GOOGLE_SHEETS_ENABLED=false`, và chỉ bật `CHANNEL_PROVIDER=web`. Bật từng tích hợp sau khi core đã chạy ổn.

Tạo tài khoản quản trị đầu tiên sau khi migration và file môi trường đã sẵn sàng:

```bash
sudo bash -c 'set -a; source /etc/donghai-bot.env; set +a; cd /opt/donghai-bot; sudo -E -u donghai .venv/bin/python -m app.scripts.create_admin_user --username admin --display-name "Quản trị viên"'
```

Lệnh sẽ yêu cầu nhập và xác nhận mật khẩu. Database chỉ lưu PBKDF2 password hash. Muốn đổi mật khẩu và thu hồi các phiên đăng nhập cũ, chạy lại với tùy chọn `--update-password`.

## 8. Cấu hình Google Sheets

Chỉ làm bước này nếu `GOOGLE_SHEETS_ENABLED=true`:

1. Tạo service account trong Google Cloud.
2. Bật Google Sheets API.
3. Tải file JSON credential vào:

   ```text
   /opt/donghai-bot/secrets/google-sheets-service-account.json
   ```

4. Phân quyền file:

   ```bash
   sudo chown donghai:donghai /opt/donghai-bot/secrets/google-sheets-service-account.json
   sudo chmod 600 /opt/donghai-bot/secrets/google-sheets-service-account.json
   ```

5. Chia sẻ Google Sheet cho email của service account với quyền Editor.
6. Tạo sheet `Orders` có ít nhất 22 cột tương ứng phạm vi `A:V`.

Nếu cấu hình Sheets không hợp lệ, ứng dụng có thể dừng ở startup vì `SheetsService.validate()` được gọi khi FastAPI khởi tạo. Vì vậy nên kiểm tra bằng test riêng trước khi bật production.

## 9. Kiểm tra source trước khi tạo service

Nạp biến môi trường vào shell để chạy smoke test:

```bash
set -a
source /etc/donghai-bot.env
set +a

cd /opt/donghai-bot
.venv/bin/python -m compileall -q app
.venv/bin/python -m unittest discover -s tests -v
```

Khởi động thử FastAPI trên localhost:

```bash
.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1
```

Ở terminal khác:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Dừng bằng `Ctrl+C` sau khi `/health` trả về JSON hợp lệ.

Có thể tải trước model CLIP để lần nhận diện ảnh đầu tiên không phải chờ tải model:

```bash
sudo -u donghai -H bash -lc '
  cd /opt/donghai-bot &&
  .venv/bin/python -c "from app.product_recognition.image_embedding_service import ImageEmbeddingService; ImageEmbeddingService(); print(\"CLIP ready\")"
'
```

## 10. Tạo systemd service cho FastAPI

Tạo `/etc/systemd/system/donghai-bot.service`:

```ini
[Unit]
Description=Dong Hai Conversation Bot FastAPI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=donghai
Group=donghai
WorkingDirectory=/opt/donghai-bot
EnvironmentFile=/etc/donghai-bot.env
ExecStart=/opt/donghai-bot/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=5
TimeoutStopSec=30
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

## 11. Tạo systemd service cho worker

Tạo `/etc/systemd/system/donghai-worker.service`:

```ini
[Unit]
Description=Dong Hai Product Sync Worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=donghai
Group=donghai
WorkingDirectory=/opt/donghai-bot
EnvironmentFile=/etc/donghai-bot.env
ExecStart=/opt/donghai-bot/.venv/bin/python -m app.workers.product_sync_worker
Restart=always
RestartSec=5
TimeoutStopSec=60
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Nạp và khởi động:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now donghai-bot donghai-worker
sudo systemctl status donghai-bot --no-pager
sudo systemctl status donghai-worker --no-pager
```

Xem log:

```bash
sudo journalctl -u donghai-bot -f
sudo journalctl -u donghai-worker -f
```

Worker chỉ in log “sẵn sàng” rồi đứng yên khi queue trống là trạng thái bình thường.

## 12. Cấu hình Nginx

Tạo `/etc/nginx/sites-available/donghai-bot`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name bot.example.com;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 15s;
        proxy_send_timeout 180s;
        proxy_read_timeout 180s;
    }
}
```

Kích hoạt:

```bash
sudo ln -s /etc/nginx/sites-available/donghai-bot /etc/nginx/sites-enabled/donghai-bot
sudo nginx -t
sudo systemctl reload nginx
```

### Bảo vệ trang quản trị

Source đã có đăng nhập database cho toàn bộ `/admin/*` bằng cookie HttpOnly được ký số. Production phải chạy migration `005_admin_users.sql`, tạo user quản trị, bật `ADMIN_AUTH_ENABLED=true`, dùng session secret ngẫu nhiên riêng và `ADMIN_COOKIE_SECURE=true`. Chỉ role `admin` được mở `/admin/users`; các trang nghiệp vụ còn lại chưa phân quyền riêng giữa `manager` và `staff`.

Có thể bổ sung Basic Auth tại Nginx như lớp bảo vệ thứ hai:

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.donghai-admin ADMIN_USER
```

Thêm block này **trước** `location /`:

```nginx
location /admin/ {
    auth_basic "Dong Hai Admin";
    auth_basic_user_file /etc/nginx/.donghai-admin;

    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 180s;
}
```

Nên bảo vệ thêm `/docs`, `/redoc`, `/openapi.json` và `/health`, hoặc giới hạn chúng theo VPN/IP quản trị. `/health` hiện có thể trả chi tiết lỗi database nên không nên public không kiểm soát.

## 13. Bật HTTPS

Cài Certbot và cấp chứng chỉ cho domain:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bot.example.com
sudo certbot renew --dry-run
```

Kiểm tra:

```bash
curl -I https://bot.example.com/
```

Telegram và Facebook yêu cầu callback HTTPS hợp lệ. Production không dùng URL ngrok vì URL có thể thay đổi và không phù hợp vận hành lâu dài.

## 14. Đăng ký Telegram webhook

Webhook của source:

```text
https://bot.example.com/api/telegram/webhook
```

Đăng ký bằng token và secret tương ứng trong `/etc/donghai-bot.env`:

```bash
curl -sS -X POST \
  "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://bot.example.com/api/telegram/webhook",
    "secret_token": "<TELEGRAM_WEBHOOK_SECRET>",
    "allowed_updates": ["message"],
    "drop_pending_updates": true
  }'
```

Kiểm tra:

```bash
curl -sS "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo"
```

Không ghi bot token thật vào tài liệu, log, ảnh chụp hoặc lịch sử Git.

## 15. Đăng ký Facebook webhook

Trong Meta Developer Dashboard:

- Callback URL: `https://bot.example.com/webhook/facebook`
- Verify token: đúng với `FACEBOOK_VERIFY_TOKEN`.
- Page access token: đúng Page đang nhận tin nhắn.
- App secret: đúng app ký header `X-Hub-Signature-256`.
- Subscribe các webhook field phục vụ tin nhắn/echo mà ứng dụng đang xử lý.

Source thực hiện:

- `GET /webhook/facebook`: xác minh callback bằng verify token.
- `POST /webhook/facebook`: xác minh HMAC bằng app secret.
- Nhận `messaging` và `standby` event.
- Bỏ qua echo do bot gửi.
- Khi nhân viên trả lời từ Meta Business Suite, bật Human mode cho khách tương ứng.

Nếu POST trả `403`, kiểm tra `FACEBOOK_APP_SECRET` và header chữ ký. Nếu GET verify trả `403`, kiểm tra `FACEBOOK_VERIFY_TOKEN` và `CHANNEL_PROVIDER` có chứa `facebook`.

## 16. Khởi tạo dữ liệu sản phẩm và Knowledge

### 16.1. Sản phẩm

1. Đảm bảo `donghai-worker` đang chạy.
2. Mở `https://bot.example.com/admin/products` và đăng nhập bằng tài khoản quản trị trong PostgreSQL.
3. Đồng bộ SKU trực tiếp, Excel hoặc “đồng bộ tất cả”.
4. Theo dõi job đến khi hoàn tất.
5. Kiểm tra database:

   ```bash
   psql "$DATABASE_URL" -c "SELECT COUNT(*) AS products FROM products WHERE status='ACTIVE';"
   psql "$DATABASE_URL" -c "SELECT COUNT(*) AS images FROM product_images WHERE is_active=TRUE;"
   psql "$DATABASE_URL" -c "SELECT COUNT(*) AS embeddings FROM product_image_embeddings;"
   ```

Chatbot đọc sản phẩm runtime từ PostgreSQL. `products.json`/snapshot không phải nguồn catalog trả lời khách.

Ảnh local trong `data/product_images` dùng để tạo và kiểm tra embedding. Ảnh gửi khách dùng `source_url` CDN Shopify.

### 16.2. Knowledge/RAG

1. Mở `/admin/knowledge`.
2. Upload TXT, Markdown hoặc PDF có text.
3. Chờ import và embedding hoàn tất.
4. Kiểm tra log startup phải có `RAG V2 ready` với số document lớn hơn 0.

Nếu đổi `RAG_EMBEDDING_PROVIDER` hoặc `RAG_EMBEDDING_MODEL`, phải tạo lại embedding tài liệu. Query embedding và document embedding khác provider/model sẽ không tìm thấy nhau dù cùng 768 chiều.

## 17. Checklist kiểm tra sau deploy

### Hạ tầng

```bash
sudo systemctl is-active nginx
sudo systemctl is-active donghai-bot
sudo systemctl is-active donghai-worker
redis-cli ping
curl -fsS http://127.0.0.1:8000/health
```

### Web

- Mở `/admin/products` trong cửa sổ riêng tư, kiểm tra bị chuyển đến `/admin/login`, đăng nhập rồi đăng xuất thành công.
- Gửi tin nhắn text qua Web chat.
- Gửi một ảnh sản phẩm đã có embedding.
- Hỏi một câu cần RAG như chính sách đổi hàng hoặc tư vấn size.
- Reset hội thoại và xác nhận Redis context bị xóa nhưng lịch sử PostgreSQL vẫn còn.

### Product worker

- Tạo một job đồng bộ SKU.
- Giao diện phải cập nhật thanh tiến độ.
- Worker có log nhận/hoàn tất job.
- Sản phẩm/variant/ảnh/embedding được cập nhật trong DB.

### Channel

- Telegram: gửi text, gửi ảnh, yêu cầu album và `/reset`.
- Facebook: gửi text, nhiều ảnh, kiểm tra echo bot và Human mode khi nhân viên trả lời.
- Kiểm tra log có `CHANNEL RESPONSE` và không có lỗi gửi media.

### Đơn hàng

- Tạo đơn đủ sản phẩm, biến thể, số lượng và thông tin nhận hàng.
- Xác nhận đơn.
- Nếu Sheets bật, kiểm tra các dòng có cùng `order_id` được ghi đúng một lần.

## 18. Sao lưu

### PostgreSQL

```bash
sudo mkdir -p /var/backups/donghai-bot
sudo chown donghai:donghai /var/backups/donghai-bot

sudo -u donghai pg_dump "$DATABASE_URL" \
  --format=custom \
  --file=/var/backups/donghai-bot/donghai_bot_$(date +%F_%H%M).dump
```

Cần kiểm thử restore định kỳ, không chỉ tạo file backup.

### Redis

- Nếu tự vận hành, bật AOF/RDB và backup thư mục dữ liệu Redis.
- Nếu dùng managed Redis, bật snapshot/backup theo chính sách nhà cung cấp.

### File

Sao lưu:

- `prompts/`
- `knowledge/`
- `data/product_images/`
- file service account Google Sheets
- `/etc/donghai-bot.env` bằng kho secret an toàn

## 19. Cập nhật phiên bản

Trình tự an toàn:

```bash
sudo systemctl stop donghai-worker

cd /opt/donghai-bot
sudo -u donghai git fetch --all
sudo -u donghai git pull --ff-only
sudo -u donghai .venv/bin/python -m pip install -r requirements.txt

set -a
source /etc/donghai-bot.env
set +a

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/001_product_catalog.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/002_product_image_embeddings.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/003_customer_care_rag.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/004_conversation_history.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_postgre/005_admin_users.sql

.venv/bin/python -m compileall -q app
.venv/bin/python -m unittest discover -s tests -v

sudo systemctl restart donghai-bot
sudo systemctl start donghai-worker
curl -fsS http://127.0.0.1:8000/health
```

Trước khi cập nhật nên backup PostgreSQL và các thư mục dữ liệu. Nếu dùng release directory/symlink, rollback source nhanh hơn; database chỉ rollback khi migration mới thực sự không tương thích và đã có kế hoạch phục hồi.

## 20. Giám sát và log

Source mặc định log ra terminal. Với systemd, dùng journal:

```bash
sudo journalctl -u donghai-bot --since "30 minutes ago"
sudo journalctl -u donghai-worker --since today
sudo journalctl -u donghai-bot -p err
```

Nên giám sát:

- `/health` và thời gian phản hồi API.
- Trạng thái hai systemd service.
- CPU/RAM/disk, đặc biệt lúc CLIP tạo embedding.
- Số job queued/running/failed trong Redis.
- Lỗi PostgreSQL/Redis.
- AI 429/503, thời gian Planner/Presenter và quota.
- Telegram/Facebook send error.
- Google Sheets 429/503 và đơn chưa export.
- Dung lượng `data/product_images` và database vector.

## 21. Các giới hạn cần xử lý trước khi scale lớn

1. **RBAC mới áp dụng cho quản lý tài khoản**: chỉ `admin` được mở `/admin/users`; nên tiếp tục giới hạn từng trang nghiệp vụ cho `manager` và `staff` khi đội vận hành mở rộng, đồng thời có thể giữ VPN/IP allowlist ở lớp Nginx.
2. **Chỉ nên dùng một Uvicorn worker**: Facebook per-recipient queue và chống trùng event đang trong RAM.
3. **Knowledge import chạy trong FastAPI background task**: job lớn có thể mất khi app restart; nên chuyển sang worker bền vững.
4. **Google Sheets không phải order database chính thức**: chỉ là kênh bàn giao để nhân viên kiểm tra.
5. **Khuyến mãi là đơn nháp do AI hỗ trợ**: nhân viên vẫn cần xác nhận trước khi tạo đơn chính thức.
6. **Local product images cần shared storage** nếu app và worker chạy ở hai máy/container khác nhau.
7. **Không deploy bằng `--reload`** và không dùng ngrok làm webhook production.

## 22. Xử lý lỗi nhanh

### App không startup

```bash
sudo systemctl status donghai-bot --no-pager
sudo journalctl -u donghai-bot -n 200 --no-pager
```

Kiểm tra lần lượt:

- `DATABASE_URL` có kết nối được không.
- AI provider có đúng API key/model không.
- Channel đã bật có đủ token/secret không.
- Google Sheets có bị bật khi credential chưa đúng không.
- RAG model/provider/dimension có khớp document trong DB không.

### Worker không xử lý job

```bash
sudo systemctl status donghai-worker --no-pager
sudo journalctl -u donghai-worker -n 200 --no-pager
redis-cli ping
```

Nếu worker chỉ đứng yên không có log mới nhưng queue trống thì không phải lỗi.

### RAG không trả lời

- Kiểm tra `RAG_ENABLED=true`.
- Kiểm tra startup log `documents=<số lớn hơn 0>`.
- Kiểm tra provider/model/dimension trong `.env` khớp tài liệu đã import.
- Re-import tài liệu sau khi đổi embedding provider/model.

### Ảnh nhận diện sai hoặc không nhận diện

- Kiểm tra `product_images.local_path` tồn tại trên máy production.
- Kiểm tra số dòng `product_image_embeddings`.
- Kiểm tra model/pretrained đang chạy khớp model/pretrained lúc tạo vector.
- Đồng bộ lại SKU và tạo embedding cho ảnh mới.

### Ảnh gửi khách bị 404

- Kiểm tra `product_images.source_url` CDN Shopify.
- Không dùng `local_path` làm URL gửi Telegram/Facebook/Web.

### Webhook nhận 200 nhưng bot không trả lời

- Kiểm tra channel có trong `CHANNEL_PROVIDER`.
- Kiểm tra Human mode của đúng channel/session.
- Kiểm tra log `CHANNEL RESPONSE` và lỗi gửi media.
- Telegram: kiểm tra `getWebhookInfo`.
- Facebook: kiểm tra page token, app secret, subscription và echo event.

## 23. Tiêu chí hoàn tất triển khai

Chỉ xem là deploy thành công khi đáp ứng đủ:

- Nginx HTTPS hoạt động và tự gia hạn chứng chỉ.
- FastAPI và worker tự khởi động lại sau reboot.
- PostgreSQL/Redis không public và có backup/persistence.
- `/admin/*` được bảo vệ.
- `/health` không báo lỗi database.
- Catalog, image embedding và RAG có dữ liệu đúng model.
- Các channel được bật đều gửi/nhận được text và ảnh.
- Human mode hoạt động đúng.
- Đơn xác nhận được lưu lịch sử và export Sheets nếu bật.
- Log/monitoring phát hiện được lỗi AI, database, Redis và channel.
