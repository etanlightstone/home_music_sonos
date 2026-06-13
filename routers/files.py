from fastapi import APIRouter, Query
from database import get_db

router = APIRouter()


def _row_to_dict(row) -> dict:
    d = dict(row)
    d['is_directory'] = bool(d['is_directory'])
    return d


def _sort_entries(entries: list[dict]) -> list[dict]:
    """Folders first, then files — both alphabetically (case-insensitive)."""
    return sorted(
        entries,
        key=lambda e: (0 if e['is_directory'] else 1, e['name'].lower())
    )


@router.get("/browse")
def browse(path: str = Query(default="/")):
    """
    List entries whose parent_path matches `path`.
    Returns folders first, then music files, both alphabetically.
    """
    conn = get_db()

    # Normalize path
    if not path:
        path = "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    rows = conn.execute(
        "SELECT * FROM entries WHERE parent_path = ? ORDER BY is_directory DESC, name COLLATE NOCASE ASC",
        (path,)
    ).fetchall()
    conn.close()

    entries = _sort_entries([_row_to_dict(r) for r in rows])
    return {"path": path, "entries": entries}


@router.get("/search")
def search(
    q: str = Query(default=""),
    type: str = Query(default="all"),  # all | files | folders
):
    """
    Case-insensitive search across name column.
    type: 'all' searches both files and dirs; 'files' only files; 'folders' only dirs.
    Returns up to 500 results, sorted folders-first then alphabetically.
    """
    if not q.strip():
        return {"query": q, "type": type, "entries": []}

    conn = get_db()
    sql = "SELECT * FROM entries WHERE name LIKE ? COLLATE NOCASE"
    params: list = [f"%{q.strip()}%"]

    if type == "files":
        sql += " AND is_directory = 0"
    elif type == "folders":
        sql += " AND is_directory = 1"

    sql += " ORDER BY is_directory DESC, name COLLATE NOCASE ASC LIMIT 500"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return {"query": q, "type": type, "entries": [_row_to_dict(r) for r in rows]}


@router.get("/folder-files")
def folder_files(path: str = Query(...)):
    """
    Return ALL music files (not directories) under a path, recursively.
    Used to build a play queue for a folder on Sonos or in-browser.
    Results are sorted by path (album/track order).
    """
    conn = get_db()

    # Normalize
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Match entries whose path starts with the given path prefix
    like_pattern = path.rstrip('/') + '/%'
    rows = conn.execute(
        """SELECT * FROM entries
           WHERE is_directory = 0
             AND (parent_path = ? OR path LIKE ?)
           ORDER BY path COLLATE NOCASE ASC""",
        (path, like_pattern)
    ).fetchall()
    conn.close()

    return {"path": path, "files": [_row_to_dict(r) for r in rows]}


@router.get("/index-check")
def index_check():
    """Quick check: are there any entries indexed?"""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    conn.close()
    return {"has_entries": count > 0, "count": count}
