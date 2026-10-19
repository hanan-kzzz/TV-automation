# Telegram AI Video Automation for MoneyPrinterTurbo

Turn your Telegram app into an AI video production studio powered by **MoneyPrinterTurbo**. Send a topic from your phone or desktop, track generation progress in real time, and receive the completed HD short video directly in Telegram for review.

---

## 📑 Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Hardware & Server Requirements](#2-hardware--server-requirements)
3. [Step 1: Create Your Telegram Bot with BotFather](#3-step-1-create-your-telegram-bot-with-botfather)
4. [Step 2: Find Your Telegram Numeric User ID](#4-step-2-find-your-telegram-numeric-user-id)
5. [Step 3: Installation & Environment Setup](#5-step-3-installation--environment-setup)
6. [Step 4: Start the Services](#6-step-4-start-the-services)
7. [Step 5: How to Use the Bot](#7-step-5-how-to-use-the-bot)
8. [Automation & Advanced Features](#8-automation--advanced-features)
9. [Troubleshooting & Diagnostics](#9-troubleshooting--diagnostics)
10. [Stopping and Restarting Services](#10-stopping-and-restarting-services)

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│               Telegram App (Phone / Desktop)           │
└───────────────────────────▲────────────────────────────┘
                            │ Long-Polling (Bot API)
┌───────────────────────────▼────────────────────────────┐
│                  telegram_bot/ (Process 1)             │
│  - handlers.py (Wizard, Commands, Rejection)           │
│  - keyboards.py (Interactive Menus)                    │
│  - job_manager.py (Queue, Concurrency, Progress, Push) │
│  - storage.py (SQLite DB: Jobs, History, User Prefs)   │
└───────────────────────────▲────────────────────────────┘
                            │ HTTP Async Client (httpx)
┌───────────────────────────▼────────────────────────────┐
│            MoneyPrinterTurbo Engine (Process 2)         │
│               uvicorn main.py (Port 8080)              │
│  - POST /api/v1/videos (Script, Terms, TTS, Video)     │
│  - GET /api/v1/tasks/{id} (State, Progress, Outputs)   │
│  - FFmpeg + MoviePy Rendering Pipeline                 │
└────────────────────────────────────────────────────────┘
```

The system runs as two decoupled, modular processes:
1. **MoneyPrinterTurbo Core Engine (`main.py`)**: The FastAPI server managing script generation (LLM), voice synthesis (TTS), stock media downloads, subtitle generation, and video composition (FFmpeg/MoviePy).
2. **Telegram Bot Runner (`telegram_bot/bot.py`)**: A non-blocking asynchronous bot communicating via MoneyPrinterTurbo's REST API. It handles user authentication, interactive inline keyboards, queue management, live status polling, deduplication, and media delivery.

---

## 2. Hardware & Server Requirements

> [!IMPORTANT]
> **Why Serverless / Edge Hosts Cannot Run This Application:**
> Video rendering combines AI script generation, TTS audio encoding, image/video filtering, and multi-track FFmpeg transcoding. A single 30–60 second video can take 1 to 5 minutes of intensive CPU and memory usage. Serverless platforms (such as Vercel, AWS Lambda, or Cloudflare Workers) have strict execution timeouts (10s–15m), limited disk space, and no persistent background workers.
>
> You **must** run both the engine and bot on a machine with a persistent operating system:
> - A local workstation (Windows 10/11, macOS, Linux)
> - A Dedicated Server or Virtual Private Server (VPS) (Ubuntu 22.04+, Debian, Fedora, Windows Server)

### Recommended Minimum Specifications:
- **CPU**: 4 cores minimum (6–8 cores recommended for faster rendering)
- **RAM**: 8 GB minimum (16 GB optimal for higher concurrency)
- **Disk Space**: At least 10–20 GB free space for source video caching and rendered tasks
- **FFmpeg**: Must be installed and accessible in the system PATH.

---

## 3. Step 1: Create Your Telegram Bot with BotFather

1. Open Telegram on your phone or desktop.
2. In the search bar, search for the verified account: **`@BotFather`**
3. Start the chat by pressing **Start** or typing `/start`.
4. Send the command:
   ```text
   /newbot
   ```
5. BotFather will prompt you for a name:
   - Example display name: `My AI Video Studio`
6. BotFather will prompt you for a username (must end in `bot`):
   - Example username: `MyMoneyPrinterVideoBot`
7. BotFather will respond with your **HTTP API Token**. It looks like:
   ```text
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   Keep this token confidential! Never share it publicly or commit it to Git.

8. *(Optional but Recommended)* Set up the command menu in BotFather:
   - Send `/setcommands` to `@BotFather`.
   - Select your bot.
   - Paste the following list of commands:
     ```text
     start - Open welcome menu and main actions
     create - Start interactive video creation
     batch - Create multiple videos from a topic list
     status - Check active and queued video jobs
     cancel - Cancel an active or queued job
     settings - Configure default language, aspect ratio, and pacing
     history - View recent completed videos
     schedule - Check automated generation schedule
     help - Show usage instructions and help
     ```

---

## 4. Step 2: Find Your Telegram Numeric User ID

For security, the bot is restricted to authorized Telegram user IDs by default.

### Method A: Using `@userinfobot` (Fastest on Mobile & Desktop)
1. In Telegram, search for **`@userinfobot`**.
2. Press **Start**.
3. The bot will immediately reply with your profile info:
   ```text
   Id: 123456789
   First: John
   ...
   ```
4. Copy the numeric **`Id`** (e.g. `123456789`).

### Method B: From the Bot Itself
If you start your MoneyPrinterTurbo bot without setting an authorized ID, it will reply with:
```text
⛔ Access Denied
Your Telegram User ID is: 123456789
Please add this ID to TELEGRAM_ALLOWED_USER_IDS in .env
```
Copy that number and paste it into your `.env` file.

---

## 5. Step 3: Installation & Environment Setup

### 1. Clone the Repository
```bash
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
```

### 2. Prepare the Python Environment (Python 3.11+)
Using `uv` (recommended):
```bash
uv sync --extra telegram
```

Or using standard `venv` and `pip`:
```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-telegram.txt
```

### 3. Configure `.env`
Copy the template `.env.example` to `.env`:
```bash
# Windows PowerShell:
Copy-Item .env.example .env

# Linux/macOS:
cp .env.example .env
```

Open `.env` in any text editor and fill in your values:
```env
# Required: Bot token from @BotFather
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz

# Required for security: Your numeric Telegram user ID
# Multiple IDs can be separated by commas: 123456789,987654321
TELEGRAM_ALLOWED_USER_IDS=123456789

# MoneyPrinterTurbo API Endpoint (Default is port 8080)
MONEYPRINTER_BASE_URL=http://127.0.0.1:8080

# If you configured an API key in config.toml under [app], specify it here:
MONEYPRINTER_API_KEY=

# Local directory where generated videos are placed
VIDEO_OUTPUT_DIR=storage/tasks

# Concurrency (1 or 2 jobs simultaneously)
MAX_CONCURRENT_JOBS=1
```

### 4. Configure MoneyPrinterTurbo LLM & Video Keys (`config.toml`)
On first launch, MoneyPrinterTurbo creates `config.toml` from `config.example.toml`.
Ensure you configure at least one LLM provider (e.g., Moonshot, OpenAI, Gemini, Claude, or Ollama) and video stock source (e.g., Pexels API key) in `config.toml` or via the WebUI (`mpt webui`).

---

## 6. Step 4: Start the Services

To enable Telegram automation, run two processes:
1. The **MoneyPrinterTurbo Core Engine**
2. The **Telegram Bot**

### Windows (Local or Desktop)

#### Method 1: 1-Click Startup Script (Fastest)
Simply double-click:
- **`start_bot.bat`**: Immediately starts both the MoneyPrinterTurbo Core Engine and Telegram Bot.
- **`start.bat`**: Interactive launcher menu (Telegram Bot, Streamlit WebUI, Full Suite, Diagnostics, and Stop Services).
- **`stop.bat`**: Cleanly shuts down all background engine and bot processes.

#### Method 2: Manual Terminal Windows
Open two PowerShell terminals:

**Terminal 1 — Core Engine:**
```powershell
.venv\Scripts\activate
python main.py
```
*(Wait until you see `start server, docs: http://127.0.0.1:8080/docs`)*

**Terminal 2 — Telegram Bot:**
```powershell
.venv\Scripts\activate
python -m telegram_bot.bot
```
*(You will see `MoneyPrinterTurbo engine is online and responsive. Starting bot long-polling...`)*

---

### Linux / VPS (Background with systemd or tmux)

#### Option A: Using `tmux`
```bash
# Terminal session 1
tmux new -s engine
source .venv/bin/activate
python main.py
# Press Ctrl+B then D to detach

# Terminal session 2
tmux new -s bot
source .venv/bin/activate
python -m telegram_bot.bot
# Press Ctrl+B then D to detach
```

#### Option B: Using systemd Services
Create `/etc/systemd/system/moneyprinter.service`:
```ini
[Unit]
Description=MoneyPrinterTurbo Engine
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/MoneyPrinterTurbo
ExecStart=/home/ubuntu/MoneyPrinterTurbo/.venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/moneyprinter-bot.service`:
```ini
[Unit]
Description=MoneyPrinterTurbo Telegram Bot
After=moneyprinter.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/MoneyPrinterTurbo
ExecStart=/home/ubuntu/MoneyPrinterTurbo/.venv/bin/python -m telegram_bot.bot
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now moneyprinter moneyprinter-bot
```

---

## 7. Step 5: How to Use the Bot

Open your bot in Telegram and start creating!

### 1. Interactive Single Video Creation (`/create`)
1. Send `/create` or tap **🎬 Create Video** from the menu.
2. **Topic**: Send your video topic or keywords (e.g. `Deep Sea Bioluminescent Creatures`).
3. **Language**: Choose your narration language:
   - 🇺🇸 **English**: Uses natural US English voice narration.
   - 🇮🇳 **Malayalam (മലയാളം)**: Uses high-definition `ml-IN-SobhanaNeural` Malayalam speech.
   - 🗣️ **Manglish**: Uses colloquial spoken Malayalam scripted in the English alphabet with Indian English voiceover.
   - 🇨🇳 **Chinese**: Uses standard Mandarin.
   - 🌐 **Auto-Detect**: Let the engine detect language automatically.
4. **Format / Aspect Ratio**:
   - 📱 **9:16 Vertical**: Best for TikTok, YouTube Shorts, Instagram Reels.
   - 🖥️ **16:9 Landscape**: Best for standard YouTube or widescreen presentation.
   - ⏹️ **1:1 Square**: Best for Instagram feed posts.
5. **Length**: Choose narration length:
   - ⚡ **Quick** (~15–30s / 1 paragraph)
   - ⏱️ **Standard** (~30–60s / 2 paragraphs)
   - 📖 **In-Depth** (~60–90s / 3 paragraphs)
   - 🎞️ **Extended** (~90–120s / 4 paragraphs)
6. **Pacing**: Choose footage change frequency (3s, 5s, or 8s).
7. **Confirmation**: Review summary and tap **🚀 Start Generation**.

### 2. Live Progress & Status Updates
The bot will update the status message in-place through each pipeline stage:
- `⚙️ Stage: Writing video script with AI (10%)`
- `⚙️ Stage: Extracting visual search terms (20%)`
- `⚙️ Stage: Synthesizing voice narration (30%)`
- `⚙️ Stage: Generating & aligning subtitles (40%)`
- `⚙️ Stage: Fetching HD video materials (50%)`
- `⚙️ Stage: Rendering & mixing final video (75%)`
- `🎬 Finishing: Video generation complete (100%)`

### 3. Video Delivery
- Once rendering completes, the bot retrieves the file from disk or API and sends it directly in the chat as a streaming video.
- You can watch, download, or forward the video immediately on your phone!
- If the video size exceeds Telegram's 50 MB bot upload limit, the bot sends a secure direct download link.

---

## 8. Automation & Advanced Features

### Sequential Batch Generation (`/batch`)
To generate multiple videos without repeating the wizard:
1. Send `/batch`.
2. Send a list of topics separated by new lines:
   ```text
   The Origins of Black Holes
   How James Webb Telescope Works
   The Search for Alien Life
   ```
3. The bot enqueues each topic. The worker renders them one by one according to your queue settings and delivers each video as it finishes.

### Per-User Preferences (`/settings`)
Change your default language, aspect ratio, length, or pacing so future `/create <topic>` or `/batch` runs automatically use your preferred defaults.

### Cancellation (`/cancel`)
- Jobs still waiting in the queue are cancelled immediately.
- Jobs currently rendering on the engine are detached from Telegram tracking.

### Crash Recovery
If the server or bot process restarts:
- When restarted, the bot scans its local SQLite database.
- Any job that finished during the downtime is immediately uploaded to the user.
- Any job still rendering on the engine re-attaches progress tracking.

### Scheduled Automation
Automate daily video generation:
1. Set `SCHEDULE_ENABLED=true` in `.env`.
2. Set `SCHEDULE_INTERVAL_HOURS=24`.
3. Set `SCHEDULE_CHAT_ID=<your-chat-id>`.
4. Set `SCHEDULE_TOPICS=Daily Tech Fact,Morning Motivation,Science Breakthrough`.
The bot will automatically generate and send a new video every 24 hours.

---

## 9. Troubleshooting & Diagnostics

| Symptom / Error | Likely Cause | Solution |
| :--- | :--- | :--- |
| **"Could not connect to MoneyPrinterTurbo"** | The engine (`python main.py`) is not running or listening on a different port. | Verify that `python main.py` is running and `MONEYPRINTER_BASE_URL` in `.env` matches `http://127.0.0.1:8080`. |
| **"Access Denied / Unauthorized"** | Your Telegram user ID is not in `TELEGRAM_ALLOWED_USER_IDS`. | Get your ID from `@userinfobot`, add it to `.env`, and restart the bot. |
| **"RuntimeError: No ffmpeg exe could be found"** | FFmpeg is not installed or not in PATH. | Install FFmpeg or set `ffmpeg_path` in `config.toml`. Check with `ffmpeg -version`. |
| **"Failed at audio / TTS timeout"** | Edge TTS network connection dropped. | Edge TTS is free but requires internet access. Verify your server can reach Microsoft TTS endpoints. |
| **"Failed at materials / no video materials found"** | Pexels/Pixabay API keys missing or search returned no footage. | Ensure `pexels_api_keys` or `pixabay_api_keys` is set in `config.toml` or WebUI. |
| **"File exceeds Telegram 50 MB limit"** | Rendered HD video is larger than 50 MB. | The bot automatically falls back to providing a direct HTTP download link. You can also shorten paragraph count. |
| **Bot not responding to messages** | Bot token invalid or process stopped. | Check terminal logs for `telegram_bot.bot`. Ensure only one bot instance is running with the token. |

---

## 10. Stopping and Restarting Services

### Stop
- In terminal: Press `Ctrl + C`. The bot and engine will perform a clean shutdown.
- With systemd:
  ```bash
  sudo systemctl stop moneyprinter-bot moneyprinter
  ```

### Restart
- With systemd:
  ```bash
  sudo systemctl restart moneyprinter moneyprinter-bot
  ```
- Or run the start commands in Terminal 1 and Terminal 2 again.
