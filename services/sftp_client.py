import paramiko
import stat as stat_module
from datetime import datetime, timezone


MUSIC_EXTENSIONS = {'mp3', 'wav', 'flac', 'aac', 'ogg', 'aiff', 'aif', 'm4a'}


class SFTPClient:
    """Synchronous SFTP client wrapper. Use as a context manager."""

    def __init__(self, settings: dict):
        self.host     = settings['server_host']
        self.port     = int(settings.get('server_port') or 22)
        self.username = settings['server_user']
        self.password = settings['server_password']
        self._ssh  = None
        self._sftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    def connect(self):
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=15,
            banner_timeout=30,
        )
        self._sftp = self._ssh.open_sftp()

    def close(self):
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._ssh:
                self._ssh.close()
        except Exception:
            pass

    def list_dir(self, path: str) -> list[dict]:
        """Return list of entries in `path`. Each entry is a dict with
        keys: name, is_dir, size, modified (ISO string or None)."""
        entries = []
        try:
            items = self._sftp.listdir_attr(path)
        except Exception as e:
            print(f"[SFTP] list_dir error for {path!r}: {e}")
            return entries

        for item in items:
            if item.filename.startswith('.'):
                continue  # skip hidden files
            is_dir = stat_module.S_ISDIR(item.st_mode) if item.st_mode else False
            modified = None
            if item.st_mtime:
                try:
                    modified = datetime.fromtimestamp(item.st_mtime, tz=timezone.utc).isoformat()
                except Exception:
                    pass
            entries.append({
                'name':    item.filename,
                'is_dir':  is_dir,
                'size':    item.st_size if not is_dir else None,
                'modified': modified,
            })
        return entries

    def read_file_chunks(self, path: str, chunk_size: int = 65536):
        """Generator yielding raw bytes chunks for streaming."""
        with self._sftp.open(path, 'rb') as f:
            f.prefetch()   # paramiko read-ahead for better throughput
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def get_file_size(self, path: str) -> int:
        return self._sftp.stat(path).st_size
