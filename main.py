# main.py - Tk-Ui-Node v2 - با پشتیبانی کامل از UDP و Xray-core
import asyncio
import json
import os
import secrets
import time
import subprocess
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Tk-Ui-Node")

app = FastAPI(title="Tk-Ui-Node", docs_url=None, redoc_url=None)

# ── Config ──────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
CONFIGS_FILE = DATA_DIR / "configs.json"
PORT = int(os.environ.get("PORT", 62050))
SERVICE_TLS = os.environ.get("SERVICE_TLS", "false").lower() == "true"
XRAY_EXECUTABLE = os.environ.get("XRAY_EXECUTABLE", "/usr/local/bin/xray")
XRAY_ASSETS = os.environ.get("XRAY_ASSETS", "/usr/local/share/xray")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

CONFIGS: dict = {}
CONFIGS_LOCK = asyncio.Lock()
XRAY_PROCESS: subprocess.Popen | None = None

# ── Load / Save ─────────────────────────────────────────────────────────────
async def load_state():
    global CONFIGS
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIGS_FILE.exists():
            with open(CONFIGS_FILE, "r") as f:
                CONFIGS = json.load(f)
        logger.info(f"Loaded {len(CONFIGS)} configs")
    except Exception as e:
        logger.warning(f"Could not load state: {e}")

async def save_state():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIGS_FILE, "w") as f:
            json.dump(CONFIGS, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save state: {e}")

# ── Xray Config Generator ──────────────────────────────────────────────────
def generate_xray_config() -> dict:
    """تولید کانفیگ کامل Xray-core از روی CONFIGS"""
    inbounds = []
    for uuid, cfg in CONFIGS.items():
        if not cfg.get("active", True):
            continue
        # بررسی انقضا
        if cfg.get("expires_at"):
            try:
                from datetime import datetime
                if datetime.now() > datetime.fromisoformat(cfg["expires_at"]):
                    continue
            except:
                pass
        # ساخت inbound برای هر کانفیگ
        inbounds.append({
            "protocol": "vless",
            "port": cfg.get("port", 443),
            "settings": {
                "clients": [{
                    "id": uuid,
                    "email": cfg.get("label", ""),
                    "flow": "xtls-rprx-vision",
                    # اجازه UDP صریحاً فعال است
                    "allowUDP": True,
                    "limit": {
                        "ip": cfg.get("ip_limit", 0) or 0,
                        "speed": cfg.get("speed_limit_bytes", 0) or 0
                    }
                }],
                "decryption": "none",
                "fallbacks": []
            },
            "streamSettings": {
                "network": "ws",
                "wsSettings": {"path": f"/ws/{uuid}", "headers": {}},
                "security": "tls",
                "tlsSettings": {
                    "alpn": [cfg.get("alpn", "http/1.1")],
                    "fingerprint": cfg.get("fingerprint", "chrome")
                }
            }
        })

    return {
        "inbounds": inbounds,
        "outbounds": [{"protocol": "freedom", "settings": {}, "tag": "direct"}],
        "routing": {"domainStrategy": "IPIfNonMatch", "rules": []}
    }

def write_xray_config(config: dict) -> Path:
    """نوشتن کانفیگ Xray در فایل موقت"""
    config_path = DATA_DIR / "xray_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    return config_path

def restart_xray():
    """ری‌استارت Xray-core با کانفیگ جدید"""
    global XRAY_PROCESS
    if XRAY_PROCESS:
        try:
            XRAY_PROCESS.terminate()
            XRAY_PROCESS.wait(timeout=5)
        except:
            XRAY_PROCESS.kill()
            XRAY_PROCESS.wait()
        XRAY_PROCESS = None
    config = generate_xray_config()
    config_path = write_xray_config(config)
    env = os.environ.copy()
    env["XRAY_LOCATION_ASSET"] = XRAY_ASSETS
    XRAY_PROCESS = subprocess.Popen(
        [XRAY_EXECUTABLE, "-c", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True
    )
    logger.info(f"Xray restarted with {len(config['inbounds'])} inbounds")

# ── API Endpoints ──────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"service": "Tk-Ui-Node", "version": "2.0", "status": "active"}

@app.get("/health")
async def health():
    return {"status": "ok", "configs": len(CONFIGS), "xray_running": XRAY_PROCESS is not None}

@app.get("/cert")
async def get_cert():
    """ارسال گواهی TLS (در صورت وجود)"""
    cert_dir = Path("/opt/marzban-node/certs")
    if cert_dir.exists():
        cert_file = cert_dir / "cert.pem"
        key_file = cert_dir / "key.pem"
        if cert_file.exists() and key_file.exists():
            return JSONResponse({
                "cert": cert_file.read_text(),
                "key": key_file.read_text()
            })
    return JSONResponse({"cert": None, "key": None}, status_code=404)

@app.post("/api/config")
async def add_or_update_config(request: Request):
    """دریافت کانفیگ از پنل اصلی"""
    body = await request.json()
    uuid = body.get("uuid")
    if not uuid:
        raise HTTPException(400, "uuid required")
    async with CONFIGS_LOCK:
        CONFIGS[uuid] = {
            "uuid": uuid,
            "label": body.get("label", "Unknown"),
            "limit_bytes": body.get("limit_bytes", 0),
            "used_bytes": body.get("used_bytes", 0),
            "expires_at": body.get("expires_at"),
            "protocol": body.get("protocol", "vless-ws"),
            "fingerprint": body.get("fingerprint", "chrome"),
            "alpn": body.get("alpn", "http/1.1"),
            "port": body.get("port", 443),
            "ip_limit": body.get("ip_limit", 0),
            "speed_limit_bytes": body.get("speed_limit_bytes", 0),
            "active": body.get("active", True),
            "updated_at": time.time(),
        }
    await save_state()
    restart_xray()
    logger.info(f"Config {uuid} updated, Xray restarted")
    return {"ok": True}

@app.delete("/api/config/{uuid}")
async def delete_config(uuid: str):
    async with CONFIGS_LOCK:
        if uuid in CONFIGS:
            del CONFIGS[uuid]
            await save_state()
            restart_xray()
            return {"ok": True}
    raise HTTPException(404, "config not found")

@app.get("/api/configs")
async def list_configs():
    return {"configs": list(CONFIGS.values())}

@app.get("/api/xray")
async def get_xray_config():
    return generate_xray_config()

# ── Startup / Shutdown ──────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    await load_state()
    restart_xray()
    logger.info(f"Tk-Ui-Node v2 started on port {PORT}")

@app.on_event("shutdown")
async def shutdown():
    if XRAY_PROCESS:
        try:
            XRAY_PROCESS.terminate()
            XRAY_PROCESS.wait(timeout=5)
        except:
            XRAY_PROCESS.kill()
            XRAY_PROCESS.wait()
    await save_state()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, log_level="info")
