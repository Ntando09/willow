# Willow v10.4

A self-healing AI companion that lives on your desktop. Willow can chat, search the web, control your computer, and repair herself when things break.

## Architecture

- **Frontend**: Next.js 16 + React Three Fiber (3D experience)
- **Backend**: FastAPI + OpenAI GPT-4o-mini + EXA search
- **Guardian**: Process monitor with auto-restart (`Willow_GUARD.py`)
- **Self-Repair**: Automated error recovery with A/B testing (`Willow_v10_4_SELF_REPAIR.py`)

## Features

- WebSocket chat with persistent personality
- Web search via EXA
- Computer use (screenshot, click, type, scroll)
- Self-monitoring guardian process
- Auto-repair with backup/rollback
- A/B testing for code changes

## Quick Start

```bash
# 1. Install frontend
npm install

# 2. Install Python backend
pip install fastapi uvicorn openai exa-py python-dotenv mss pyautogui pillow

# 3. Configure environment
cp .env.example .env
# Edit .env with your real keys

# 4. Start everything
python Willow_GUARD.py
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /device-status` | System info |
| `POST /search` | EXA web search |
| `POST /computer-use` | Control mouse/keyboard |
| `GET /repair-logs` | View self-repair history |
| `WS /ws` | Chat WebSocket |

## Project Structure

```
WILLOW/
├── backend/
│   ├── __init__.py
│   └── main.py
├── src/
│   ├── app/
│   │   ├── globals.css
│   │   ├── layout.tsx
│   │   └── page.tsx
│   └── components/
│       ├── WillowExperience.tsx
│       └── Phase2Panels.tsx
├── Willow_GUARD.py
├── Willow_v10_4_SELF_REPAIR.py
├── .env.example
└── package.json
```

## Note

This is a personal project with machine-specific paths. Adjust for your own setup before running.
