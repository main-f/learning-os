"""Separate Telegram bot: unique token, strict chat allowlist, outbound polling only."""
import json
import os
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from .database import connect, initialize

TOKEN = os.getenv("STUDY_TELEGRAM_BOT_TOKEN", "")
ALLOWED_CHAT = os.getenv("STUDY_TELEGRAM_ALLOWED_CHAT_ID", "")


def telegram(method: str, params: dict) -> dict:
    if not TOKEN:
        raise RuntimeError("Missing STUDY_TELEGRAM_BOT_TOKEN")
    data = urlencode(params).encode("utf-8")
    with urlopen(f"https://api.telegram.org/bot{TOKEN}/{method}", data=data, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {method}")
    return payload


def send(message: str) -> None:
    if not ALLOWED_CHAT:
        raise RuntimeError("Missing STUDY_TELEGRAM_ALLOWED_CHAT_ID")
    telegram("sendMessage", {"chat_id":ALLOWED_CHAT,"text":message})


def today_text() -> str:
    initialize()
    with connect() as db:
        row = db.execute("SELECT id,title,minutes FROM tasks WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()
    if row is None:
        return "当前没有待办任务。今天的学习成果已记录！"
    return f"今日执行命令：{row['title']}（至少 {row['minutes']} 分钟）\n完成后向我发送 /done 及简短的学习成果。"


def handle_message(chat_id: str, text: str) -> None:
    if chat_id != ALLOWED_CHAT:
        return
    if text.strip().startswith(("/start", "/today")):
        send(today_text())
    elif text.strip().startswith("/done"):
        note = text.strip().removeprefix("/done").strip()
        if len(note) < 5:
            send("请在 /done 后面写下至少 5 个字符的学习成果，例如：/done 完成了 DDoS 的 5 道测试题")
            return
        initialize()
        with connect() as db:
            row = db.execute("SELECT id FROM tasks WHERE status='pending' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                send("已没有待办任务。")
                return
            from datetime import datetime, timezone
            import uuid
            timestamp = datetime.now(timezone.utc).isoformat()
            sid = str(uuid.uuid4())
            db.execute("INSERT INTO study_sessions VALUES (?,?,?,?,?,?)",(sid,row['id'],0,note,"study",timestamp))
            db.execute("UPDATE tasks SET status='completed',completed_at=? WHERE id=?",(timestamp,row['id']))
            db.execute("INSERT INTO event_outbox VALUES (?,?,?,?)", (
                str(uuid.uuid4()),"study.session_recorded",
                json.dumps({"session_id":sid,"task_id":row['id'],"source":"telegram","self_reported":True}),timestamp))
        send("漂亮，学习成果已记录！实际学习时长未核实；这不是官方成绩或能力评估。")


def poll() -> None:
    if not ALLOWED_CHAT or not TOKEN:
        raise RuntimeError("Set STUDY_TELEGRAM_BOT_TOKEN and STUDY_TELEGRAM_ALLOWED_CHAT_ID")
    offset = None
    while True:
        try:
            params={"timeout":25,"allowed_updates":json.dumps(["message"])}
            if offset is not None: params["offset"]=offset
            result = telegram("getUpdates", params)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or {}
                chat = msg.get("chat") or {}
                if chat.get("id") is not None:
                    handle_message(str(chat["id"]),msg.get("text", ""))
        except Exception as ex:
            # Never log token or user message contents.
            print(f"study bot retry: {type(ex).__name__}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    poll()
