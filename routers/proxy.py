from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from urllib.parse import unquote
import socket

router = APIRouter()

CONTENT_TYPES = {
    'mp3':  'audio/mpeg',
    'wav':  'audio/wav',
    'flac': 'audio/flac',
    'aac':  'audio/aac',
    'ogg':  'audio/ogg',
    'm4a':  'audio/mp4',
    'aiff': 'audio/aiff',
    'aif':  'audio/aiff',
}


def get_base_url(settings: dict) -> str:
    """Build http://ip:port base URL for this server (LAN-accessible)."""
    host = settings.get("webserver_host", "").strip()
    if not host:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            host = f"{ip}:8000"
        except Exception:
            host = "localhost:8000"
    return f"http://{host}"


def build_proxy_url(rel_path: str, settings: dict) -> str:
    """Build the full proxy URL for a relative path (for Sonos to call)."""
    base = get_base_url(settings)
    safe_path = rel_path.lstrip('/')
    return f"{base}/api/proxy/{safe_path}"


def _make_client(settings: dict):
    if settings['server_type'] == 'sftp':
        from services.sftp_client import SFTPClient
        return SFTPClient(settings)
    else:
        from services.ftp_client import FTPClient
        return FTPClient(settings)


@router.get("/{file_path:path}")
async def proxy_audio(file_path: str):
    """
    Stream an audio file from the remote server.
    file_path is the relative path (matching entries.path without leading slash).
    The proxy prepends server_path from settings.
    """
    from routers.settings import get_settings
    settings = get_settings()

    if not settings.get('server_host'):
        raise HTTPException(status_code=503, detail="Server not configured")

    # Decode URL-encoded characters
    decoded_path = unquote(file_path)

    # Build absolute path on remote server
    server_root = settings.get('server_path', '/').rstrip('/')
    abs_path = f"{server_root}/{decoded_path.lstrip('/')}"

    # Determine content type
    ext = decoded_path.rsplit('.', 1)[-1].lower() if '.' in decoded_path else ''
    content_type = CONTENT_TYPES.get(ext, 'application/octet-stream')

    client = _make_client(settings)

    # Try to get file size for Content-Length (helps Sonos and browser scrubbing)
    headers = {}
    try:
        client.connect()
        size = client.get_file_size(abs_path)
        headers['Content-Length'] = str(size)
        headers['Accept-Ranges'] = 'bytes'
    except Exception:
        try:
            client.close()
        except Exception:
            pass
        client = _make_client(settings)
        try:
            client.connect()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Cannot connect to server: {e}")

    def stream_generator():
        try:
            yield from client.read_file_chunks(abs_path)
        except Exception as e:
            print(f"[Proxy] Stream error for {abs_path!r}: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass

    return StreamingResponse(
        stream_generator(),
        media_type=content_type,
        headers=headers,
    )
