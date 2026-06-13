import ftplib
import io
from datetime import datetime, timezone


class FTPClient:
    """Synchronous FTP client wrapper. Use as a context manager."""

    def __init__(self, settings: dict):
        self.host     = settings['server_host']
        self.port     = int(settings.get('server_port') or 21)
        self.username = settings['server_user']
        self.password = settings['server_password']
        self._ftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    def connect(self):
        self._ftp = ftplib.FTP()
        self._ftp.connect(self.host, self.port, timeout=15)
        self._ftp.login(self.username, self.password)
        self._ftp.set_pasv(True)

    def close(self):
        try:
            self._ftp.quit()
        except Exception:
            pass

    def list_dir(self, path: str) -> list[dict]:
        """Return list of entries. Uses MLSD if available, falls back to LIST."""
        entries = []
        try:
            # Try MLSD (modern, gives reliable metadata)
            for name, facts in self._ftp.mlsd(path):
                if name in ('.', '..') or name.startswith('.'):
                    continue
                is_dir = facts.get('type', '') == 'dir'
                size_str = facts.get('size', '')
                size = int(size_str) if size_str and not is_dir else None
                modified = None
                modify = facts.get('modify', '')
                if modify and len(modify) >= 14:
                    try:
                        modified = datetime(
                            int(modify[0:4]), int(modify[4:6]), int(modify[6:8]),
                            int(modify[8:10]), int(modify[10:12]), int(modify[12:14]),
                            tzinfo=timezone.utc
                        ).isoformat()
                    except Exception:
                        pass
                entries.append({'name': name, 'is_dir': is_dir, 'size': size, 'modified': modified})
        except ftplib.error_perm:
            # Fall back to LIST
            lines = []
            try:
                self._ftp.retrlines(f'LIST {path}', lines.append)
            except Exception as e:
                print(f"[FTP] list_dir error for {path!r}: {e}")
                return entries
            for line in lines:
                parts = line.split(None, 8)
                if len(parts) < 9:
                    continue
                name = parts[8].strip()
                if name in ('.', '..') or name.startswith('.'):
                    continue
                is_dir = line.startswith('d')
                size = None
                try:
                    if not is_dir:
                        size = int(parts[4])
                except (ValueError, IndexError):
                    pass
                entries.append({'name': name, 'is_dir': is_dir, 'size': size, 'modified': None})
        return entries

    def read_file_chunks(self, path: str, chunk_size: int = 65536):
        """Read entire file into memory then yield chunks.
        Note: FTP doesn't support true streaming easily in a generator context.
        For large files this will consume memory — acceptable for LAN use."""
        buf = io.BytesIO()
        self._ftp.retrbinary(f'RETR {path}', buf.write)
        buf.seek(0)
        while True:
            chunk = buf.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def get_file_size(self, path: str) -> int:
        return self._ftp.size(path)
