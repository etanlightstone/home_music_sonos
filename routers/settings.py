from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from database import get_db

router = APIRouter()

DEFAULTS = {
    "sonos_ip":       "10.0.1.90",
    "server_type":    "sftp",
    "server_host":    "",
    "server_port":    "22",
    "server_user":    "",
    "server_password": "",
    "server_path":    "/",
    "webserver_host": "",
}

class SettingsUpdate(BaseModel):
    sonos_ip:        Optional[str] = None
    server_type:     Optional[str] = None
    server_host:     Optional[str] = None
    server_port:     Optional[str] = None
    server_user:     Optional[str] = None
    server_password: Optional[str] = None
    server_path:     Optional[str] = None
    webserver_host:  Optional[str] = None

@router.get("")
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    result = dict(DEFAULTS)
    for row in rows:
        result[row["key"]] = row["value"]
    return result

@router.post("")
def update_settings(data: SettingsUpdate):
    conn = get_db()
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    with conn:
        for key, value in updates.items():
            if key in DEFAULTS:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, value)
                )
    conn.close()
    return get_settings()
