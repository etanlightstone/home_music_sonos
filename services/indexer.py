import asyncio
from datetime import datetime, timezone
from database import get_db

MUSIC_EXTENSIONS = {'mp3', 'wav', 'flac', 'aac', 'ogg', 'aiff', 'aif', 'm4a'}

_task: asyncio.Task | None = None
_cancel_flag = asyncio.Event()   # set -> stop indexing


def _get_settings():
    """Read settings synchronously from DB."""
    from routers.settings import get_settings
    return get_settings()


def _make_client(settings: dict):
    """Return the right client instance (not yet connected)."""
    if settings['server_type'] == 'sftp':
        from services.sftp_client import SFTPClient
        return SFTPClient(settings)
    else:
        from services.ftp_client import FTPClient
        return FTPClient(settings)


def is_music_file(name: str) -> bool:
    if '.' not in name:
        return False
    return name.rsplit('.', 1)[-1].lower() in MUSIC_EXTENSIONS


def _update_status(**kwargs):
    """Synchronous DB status update (called from executor or main thread)."""
    conn = get_db()
    sets = ', '.join(f"{k}=?" for k in kwargs)
    with conn:
        conn.execute(f"UPDATE index_status SET {sets} WHERE id=1", list(kwargs.values()))
    conn.close()


def get_status() -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM index_status WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {}


async def start_indexing() -> bool:
    """Start background indexing. Returns False if already running."""
    global _task, _cancel_flag
    if _task and not _task.done():
        return False
    _cancel_flag.clear()
    _task = asyncio.create_task(_run_indexing())
    return True


async def interrupt_indexing():
    """Cancel indexing and clear the entries table."""
    global _task, _cancel_flag
    _cancel_flag.set()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM entries")
        conn.execute("""UPDATE index_status SET
            is_running=0, completed_at=NULL, was_interrupted=1,
            total_entries=0, processed_entries=0 WHERE id=1""")
    conn.close()


async def _run_indexing():
    """Main indexing coroutine."""
    settings = _get_settings()
    now = datetime.now(tz=timezone.utc).isoformat()

    conn = get_db()
    with conn:
        conn.execute("DELETE FROM entries")
        conn.execute("""UPDATE index_status SET
            is_running=1, started_at=?, completed_at=NULL,
            was_interrupted=0, total_entries=0, processed_entries=0
            WHERE id=1""", (now,))
    conn.close()

    loop = asyncio.get_event_loop()
    client = _make_client(settings)

    try:
        # Connect in thread pool (blocking)
        await loop.run_in_executor(None, client.connect)
        server_root = settings.get('server_path', '/').rstrip('/') or '/'
        await _index_dir(loop, client, server_root, server_root, '/')
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[Indexer] Fatal error: {e}")
    finally:
        try:
            await loop.run_in_executor(None, client.close)
        except Exception:
            pass
        _update_status(
            is_running=0,
            completed_at=datetime.now(tz=timezone.utc).isoformat()
        )


async def _index_dir(loop, client, server_root: str, abs_path: str, rel_path: str):
    """Recursively index one directory.
    - server_root: the configured server_path (e.g. /home/music)
    - abs_path:    absolute path on server (e.g. /home/music/Rock)
    - rel_path:    relative path stored in DB (e.g. /Rock)
    """
    if _cancel_flag.is_set():
        return

    # List directory in thread pool
    try:
        entries = await loop.run_in_executor(None, client.list_dir, abs_path)
    except Exception as e:
        print(f"[Indexer] list_dir failed for {abs_path!r}: {e}")
        return

    # Separate dirs and files
    dirs  = [e for e in entries if e['is_dir']]
    files = [e for e in entries if not e['is_dir'] and is_music_file(e['name'])]

    # Build batch for DB insert
    batch = []
    for d in dirs:
        child_rel = (rel_path.rstrip('/') + '/' + d['name']).replace('//', '/')
        batch.append((child_rel, d['name'], rel_path, 1, None, d.get('modified'), None))
    for f in files:
        child_rel = (rel_path.rstrip('/') + '/' + f['name']).replace('//', '/')
        ext = f['name'].rsplit('.', 1)[-1].lower()
        batch.append((child_rel, f['name'], rel_path, 0, f.get('size'), f.get('modified'), ext))

    if batch:
        conn = get_db()
        with conn:
            conn.executemany("""
                INSERT OR REPLACE INTO entries
                    (path, name, parent_path, is_directory, size, modified, extension)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.execute(
                "UPDATE index_status SET processed_entries = processed_entries + ? WHERE id=1",
                (len(batch),)
            )
        conn.close()

    # Yield to event loop
    await asyncio.sleep(0)

    # Recurse into subdirectories
    for d in dirs:
        if _cancel_flag.is_set():
            break
        child_abs = (abs_path.rstrip('/') + '/' + d['name']).replace('//', '/')
        child_rel = (rel_path.rstrip('/') + '/' + d['name']).replace('//', '/')
        await _index_dir(loop, client, server_root, child_abs, child_rel)
        await asyncio.sleep(0)
