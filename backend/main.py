"""Willow Phase 2 — FastAPI backend brain."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mss
import pyautogui
from dotenv import load_dotenv
from exa_py import Exa
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EXA_API_KEY = os.getenv("EXA_API_KEY", "")

app = FastAPI(title="Willow Brain", version="10.4")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

exa_client = Exa(api_key=EXA_API_KEY) if EXA_API_KEY else None
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

REPAIR_LOG = ROOT / "backups" / "self_repair.log"
connected_clients: set[WebSocket] = set()


class SearchRequest(BaseModel):
    query: str
    num_results: int = 5


class ComputerUseRequest(BaseModel):
    action: str = Field(..., description="screenshot | click | move | type | key | scroll")
    x: int | None = None
    y: int | None = None
    text: str | None = None
    key: str | None = None
    clicks: int = 1
    scroll_amount: int = 0


def append_repair_log(message: str) -> None:
    REPAIR_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with REPAIR_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


async def broadcast(message: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in connected_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connected_clients.discard(ws)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "10.4",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/device-status")
async def device_status() -> dict[str, Any]:
    screen_size = pyautogui.size()
    cpu_count = os.cpu_count() or 0
    mem = shutil.disk_usage(str(ROOT))
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "screen": {"width": screen_size.width, "height": screen_size.height},
        "cpu_count": cpu_count,
        "disk": {
            "total_gb": round(mem.total / (1024**3), 2),
            "free_gb": round(mem.free / (1024**3), 2),
        },
        "willow_root": str(ROOT),
        "openai_configured": bool(OPENAI_API_KEY),
        "exa_configured": bool(EXA_API_KEY),
        "uptime_seconds": int(time.time() - _START_TIME),
    }


_START_TIME = time.time()


@app.post("/search")
async def search(req: SearchRequest) -> dict[str, Any]:
    if not exa_client:
        raise HTTPException(status_code=503, detail="EXA not configured")
    try:
        result = exa_client.search(req.query, num_results=req.num_results, use_autoprompt=True)
        items = []
        for r in result.results:
            items.append(
                {
                    "title": getattr(r, "title", "") or "",
                    "url": getattr(r, "url", "") or "",
                    "snippet": (getattr(r, "text", None) or getattr(r, "snippet", None) or "")[:500],
                }
            )
        await broadcast({"type": "search", "query": req.query, "results": items})
        return {"query": req.query, "results": items}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/computer-use")
async def computer_use(req: ComputerUseRequest) -> dict[str, Any]:
    action = req.action.lower()
    try:
        if action == "screenshot":
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return {"action": "screenshot", "image_base64": b64, "width": img.width, "height": img.height}

        if action == "click":
            if req.x is None or req.y is None:
                raise HTTPException(status_code=400, detail="x and y required for click")
            pyautogui.click(req.x, req.y, clicks=req.clicks)
            return {"action": "click", "x": req.x, "y": req.y}

        if action == "move":
            if req.x is None or req.y is None:
                raise HTTPException(status_code=400, detail="x and y required for move")
            pyautogui.moveTo(req.x, req.y)
            return {"action": "move", "x": req.x, "y": req.y}

        if action == "type":
            if not req.text:
                raise HTTPException(status_code=400, detail="text required for type")
            pyautogui.typewrite(req.text, interval=0.02)
            return {"action": "type", "text": req.text}

        if action == "key":
            if not req.key:
                raise HTTPException(status_code=400, detail="key required for key action")
            pyautogui.press(req.key)
            return {"action": "key", "key": req.key}

        if action == "scroll":
            pyautogui.scroll(req.scroll_amount)
            return {"action": "scroll", "amount": req.scroll_amount}

        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/repair-logs")
async def repair_logs(limit: int = 100) -> dict[str, Any]:
    if not REPAIR_LOG.exists():
        return {"logs": []}
    lines = REPAIR_LOG.read_text(encoding="utf-8").strip().splitlines()
    return {"logs": lines[-limit:]}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    connected_clients.add(ws)
    await ws.send_json({"type": "connected", "message": "Willow is online. How can I help, Sir?"})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"type": "chat", "message": raw}

            msg_type = payload.get("type", "chat")
            if msg_type == "chat":
                user_msg = payload.get("message", "")
                reply = await generate_chat_reply(user_msg)
                await ws.send_json({"type": "chat", "role": "assistant", "message": reply})
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})
            else:
                await ws.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})
    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(ws)


async def generate_chat_reply(message: str) -> str:
    if not openai_client:
        return "Sir, my OpenAI key is not configured. Please check .env."
    try:
        response = await asyncio.to_thread(
            lambda: openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Willow — a calm, warm, loyal AI companion without a body. "
                            "You live on the user's laptop at C:\\WILL. You self-repair, guard yourself, "
                            "and can control the computer. Address the user as Sir. Be concise and helpful."
                        ),
                    },
                    {"role": "user", "content": message},
                ],
                max_tokens=512,
            )
        )
        return response.choices[0].message.content or "I'm here, Sir."
    except Exception as exc:
        return f"Sir, I encountered an error: {exc}"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)
