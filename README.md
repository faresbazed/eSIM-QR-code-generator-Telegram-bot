# 📱 eSIM QR Code, LPA & Direct Link Converter Telegram Bot

A complete, production-ready Telegram bot that converts **eSIM QR Code images**, **LPA strings**, or **Apple/Android direct installation links** into a full installation message containing:

- 🖼️ **High-Contrast Scannable QR Code**
- 🖥️ **SM-DP+ Server Address** (one-tap copyable `<code>`)
- 🔑 **Activation Code / Matching ID** (one-tap copyable `<code>`)
- 📋 **Full Manual LPA Code** (`LPA:1$...`)
- 🔗 **Apple iOS & Android Direct Provisioning Links** (`https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=...` & `https://esimsetup.android.com/esim_qrcode_provisioning?carddata=...`)
- 📲 **Direct Installation Inline Buttons** (`📲 تركيب على الأيفون` / `🤖 تركيب على الأندرويد`)
- 🌐 **3 Languages Built-In**: **Arabic (Default)** 🇸🇦, **English** 🇺🇸, and **Chinese** 🇨🇳
- 🛡️ **Full Admin Control Panel & Message Forwarding**: Forwards all user messages and conversions to the Bot Owner (`OWNER_ID`), with interactive buttons and commands for banning/unbanning users, messaging individual users, broadcasting to all users, viewing bot statistics, and exporting user lists.

## ✨ Key Features

### 1. Universal eSIM Conversion (3-in-1)
Users can send any of the following in chat:
1. **QR Code Image / Screenshot**: Decoded automatically via OpenCV multi-pass preprocessing (handles standard, cropped, and dark-mode screenshots).
2. **LPA String**: e.g. `LPA:1$rsp.truphone.com$QRF-SPEEDTEST-PMRDGIR2EARDCIT5`
3. **Direct Installation Link**: e.g. `https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=LPA:1$rsp.truphone.com$QRF-SPEEDTEST-PMRDGIR2EARDCIT5` or Android equivalent.

The bot replies with a newly generated QR Code photo, copyable `SM-DP+` and `Activation Code` fields, full `LPA` string, clickable iOS/Android provisioning URLs, a browser warning note, and two direct installation inline buttons.

### 2. Multi-Language Support (Arabic Default, English, Chinese)
- Defaults to **Arabic (`ar`)** out of the box.
- Users can switch between **العربية 🇸🇦**, **English 🇺🇸**, and **中文 🇨🇳** at any time via `/start` or `/lang`.

### 3. Automatic Interactive Setup (`BOT_TOKEN` & `OWNER_ID`)
You can configure your bot in **three ways**:
1. **Interactive Terminal Prompt**: Run `python bot.py` on any terminal/VPS/hosting console—if `BOT_TOKEN` or `OWNER_ID` is not set, the script prompts you directly and saves them to `config.json`.
2. **Web Setup Wizard**: If deployed on a cloud PaaS (Render, Railway, Koyeb, Heroku, Fly.io) without environment variables pre-filled, visit your app's web URL to enter your `BOT_TOKEN` and `OWNER_ID` in a clean browser form.
3. **Environment Variables / `.env`**: Set `BOT_TOKEN` and `OWNER_ID` in `.env` or your hosting dashboard.

### 4. Owner Message Forwarding & Admin Control Panel
- Every message, photo, or eSIM conversion performed by any user is forwarded to the **Owner (`OWNER_ID`)** with quick inline `[✉️ رد على المستخدم]` and `[🚫 حظر المستخدم]` buttons.
- You can also **Reply** directly to any forwarded message in Telegram and the bot will deliver your reply to that user.

#### Admin Commands
| Command | Description |
| :--- | :--- |
| `/admin` or `/panel` | Open the interactive **Admin Control Panel** with inline buttons |
| `/ban <user_id> [reason]` | Ban a user from using the bot (with optional reason) |
| `/unban <user_id>` | Unban a previously banned user |
| `/send <user_id> <message>` | Send a private message to a specific user |
| `/broadcast <message>` | Send a public announcement to all bot users (or reply to any photo/message with `/broadcast`) |
| `/stats` | View total users, active/banned counts, language breakdown, and total eSIM conversions |
| `/users` | Browse paginated user list and export all users as a `.csv` file |

## 🚀 Quick Start & Deployment

### Option 1: Run Locally or on Any Python Hosting / VPS
```bash
git clone https://github.com/YOUR_USERNAME/esim-telegram-bot.git
cd esim-telegram-bot
pip install -r requirements.txt
python bot.py
```
When started for the first time, it will ask for your **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather)) and your **Owner Telegram ID** (from [@userinfobot](https://t.me/userinfobot)).

### Option 2: Deploy to Render / Railway / Heroku / Koyeb
1. Upload all files in this repository to GitHub.
2. Connect the GitHub repository to **Render**, **Railway**, **Koyeb**, or **Heroku**.
3. Either set `BOT_TOKEN` and `OWNER_ID` in the hosting Environment Variables, **or** open the deployed web URL in your browser to fill in the setup form directly.

## 📁 Repository Structure
- `bot.py` — Complete Telegram bot source code (eSIM parser, QR decoder/generator, 3-language translations, SQLite database, admin panel, and setup server)
- `requirements.txt` — Python dependencies
- `.env.example` — Environment variable template
- `Procfile` — Process file for Railway / Heroku / PaaS platforms
- `Dockerfile` — Container build file for Docker-based hosts
- `render.yaml` — One-click Render blueprint configuration
- `README.md` — Documentation and setup guide
