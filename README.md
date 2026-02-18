# VideoMemory

A video monitoring system that uses vision-language models to analyse camera feeds. You create **tasks** describing what to watch for, and the system continuously analyses the video stream — counting events, detecting conditions, and triggering actions like Discord notifications.

<video src="https://private-user-images.githubusercontent.com/57735073/551389107-97940b8e-33de-4dd1-84c1-0171b7d5146e.mov?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NzEzOTk1NTUsIm5iZiI6MTc3MTM5OTI1NSwicGF0aCI6Ii81NzczNTA3My81NTEzODkxMDctOTc5NDBiOGUtMzNkZS00ZGQxLTg0YzEtMDE3MWI3ZDUxNDZlLm1vdj9YLUFtei1BbGdvcml0aG09QVdTNC1ITUFDLVNIQTI1NiZYLUFtei1DcmVkZW50aWFsPUFLSUFWQ09EWUxTQTUzUFFLNFpBJTJGMjAyNjAyMTglMkZ1cy1lYXN0LTElMkZzMyUyRmF3czRfcmVxdWVzdCZYLUFtei1EYXRlPTIwMjYwMjE4VDA3MjA1NVomWC1BbXotRXhwaXJlcz0zMDAmWC1BbXotU2lnbmF0dXJlPWExNzYxMzBkYTc0NTc0YzAxMjQ4OTA5YzliMzcyOTQyNzY2OGU1N2Q3ODFiM2NhNDRlNjc5OTllZmZhYmNmNTMmWC1BbXotU2lnbmVkSGVhZGVycz1ob3N0In0.pNsHNw0P10xd3ve2Q5nq_hlI9Rc08MyeVEEu3yT7CaY" controls width="640"></video>

## Quick Start

```bash
uv run flask_app/app.py
```

Open http://localhost:5050. Set your model API key in the **Settings** tab. Chat with the admin agent in the **Chat** tab to manage the system through natural conversation, or browse your cameras and monitoring tasks directly in the **Devices** and **Tasks** tabs.

## Telegram

Text the system from anywhere — your phone, laptop, tablet — through Telegram. Send messages and receive real-time updates from your monitoring tasks on any device, wherever you are.

Create a bot with **@BotFather** in Telegram, paste the **Bot Token** in Settings, then restart the app. Open a chat with your bot and send a message to add tasks, list devices, and so on. The app uses long polling by default (no public URL needed). With a public URL you can set the bot webhook to `https://your-server/api/telegram/webhook` instead.

## CLI Mode

```bash
uv run videomemory/main.py
```

Same admin agent, but in your terminal. Requires a `GOOGLE_API_KEY` environment variable or `.env` file.

---

## Raspberry Pi Deployment

SSH into your Pi and run:

```bash
curl -sSL https://raw.githubusercontent.com/Clamepending/videomemory/main/deploy/setup-pi.sh | bash
```

This installs VideoMemory as a background service that starts on boot. When it finishes it prints the URL (e.g. `http://192.168.1.42:5050`). Open it and set your API key in the **Settings** tab.

```bash
sudo systemctl status videomemory     # check status
sudo systemctl restart videomemory    # restart
sudo journalctl -u videomemory -f     # view logs
```

---

## OpenClaw Agent Setup

1. Install [OpenClaw](https://openclaw.ai/)
2. Tell your agent:

> Clone https://github.com/Clamepending/videomemory and read the `AGENTS.md` file to onboard to the VideoMemory system.

If VideoMemory is already running on a Pi or other machine, add the server URL:

> The VideoMemory server is running at http://YOUR_PI_IP:5050. Read the `AGENTS.md` file at https://github.com/Clamepending/videomemory to onboard.
