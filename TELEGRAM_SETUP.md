# Cấu hình Telegram

Thêm các biến sau vào file `.env` của dự án:

```env
CHANNEL_PROVIDER=web,telegram
TELEGRAM_BOT_TOKEN=BOT_ID:TOKEN_TU_BOTFATHER
TELEGRAM_WEBHOOK_SECRET=dong_hai_telegram_secret
```

Chạy FastAPI, sau đó mở tunnel HTTPS đến đúng cổng FastAPI:

```powershell
ngrok http 8010
```

Đăng ký webhook trong PowerShell (không ghi token trực tiếp vào source):

```powershell
$secureToken = Read-Host "Token BotFather" -AsSecureString
$token = [System.Net.NetworkCredential]::new("", $secureToken).Password
$secret = "dong_hai_telegram_secret"
$ngrokUrl = "https://URL-CUA-BAN.ngrok-free.app"
$body = @{
  url = "$ngrokUrl/api/telegram/webhook"
  secret_token = $secret
  allowed_updates = @("message")
  drop_pending_updates = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "https://api.telegram.org/bot$token/setWebhook" `
  -ContentType "application/json" -Body $body
```

Kiểm tra webhook:

```powershell
Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/getWebhookInfo"
```

Các key Redis được tách theo nguồn:

```text
donghai:conversation:web:{session_id}
donghai:conversation:telegram:{chat_id}
```

Gửi `/reset` hoặc `/new` trong Telegram để xóa ngữ cảnh Telegram của chat đó.

## Kiến trúc channel

`CHANNEL_PROVIDER` là biến duy nhất quyết định các kênh được bật:

```env
CHANNEL_PROVIDER=web
CHANNEL_PROVIDER=telegram
CHANNEL_PROVIDER=web,telegram
```

Mọi kênh đều tạo `IncomingChannelMessage` rồi đi qua
`app/channels/dispatcher.py`. Provider chỉ làm nhiệm vụ nhận/gửi dữ liệu của
nền tảng; không chứa logic tư vấn, giỏ hàng hoặc RAG.

Khi bổ sung Facebook, tạo provider thực hiện contract trong
`app/channels/base.py`, đăng ký trong `app/channels/factory.py`, rồi thêm
`facebook` vào danh sách provider được hỗ trợ và `.env`:

```env
CHANNEL_PROVIDER=web,telegram,facebook
```
