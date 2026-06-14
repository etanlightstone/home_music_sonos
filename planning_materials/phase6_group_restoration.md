# Group Restoration Plan

## The Problem

When speakers are grouped together and then the group breaks (a speaker goes offline,
reconnects to a different network, or is manually ungrouped), our app still has the
Sonos IP configured — but that IP may no longer be part of the expected group.

Playback still works because `play_uri()` routes through whatever coordinator exists,
but volume control silently targets the wrong speaker (or just the solo speaker),
and the UI has no idea the group changed.

## The Goal

1. **Detect** when the configured speaker is no longer in its saved group.
2. **Restore** the group automatically by having each member rejoin the coordinator.
3. **Persist** the group configuration so it survives app restarts and network changes.
4. **Gracefully degrade** if the coordinator is offline or a member can't rejoin.

## How Sonos Groups Work

In soco, a group is identified by a `ZoneGroup` object:

```python
group = player.group
# group.uid       → 'RINCON_000FD584236D01400:58'  (unique group ID)
# group.coordinator → SoCo("10.0.1.90")             (the leader)
# group.members     → {SoCo("10.0.1.90"), SoCo("10.0.1.91"), ...}  (all members)
```

Key facts:
- `player.group` returns `None` if the speaker is solo (not in any group).
- `player.group` returns `None` if the speaker is a stereo-pair slave (controls master instead).
- `member.join(coordinator)` — joins a speaker to a group led by `coordinator`.
- `player.unjoin()` — removes a speaker from its current group.
- The group `uid` is stable as long as the group exists and the coordinator hasn't changed.

## Data Model

Add two new fields to the settings table:

| Field | Type | Description |
|---|---|---|
| `sonos_group_coordinator` | string | IP of the group coordinator (leader) |
| `sonos_group_members` | string | JSON array of member IPs, e.g. `["10.0.1.90", "10.0.1.91", "10.0.1.92"]` |

The coordinator IP is always included in the members list (the members list is the full roster).

On first use, the app scans all Sonos devices on the network, asks each one what group it's in,
and saves the coordinator + members. The user can also manually save the current group via a
new `/api/sonos/save-group` endpoint.

## Flow

```
App starts / User presses Play
        │
        ▼
  Load settings
  Check sonos_group_coordinator exists?
        │
   Yes ─┴──► Is configured IP in saved group?
        │          │
        │     player.group is not None
        │          │
        │     group.uid matches saved uid?
        │          │
        │   Yes ───┴──► Play normally (group is intact)
        │
        │   No ──────► Group is broken or changed
        │              │
        │              ▼
        │         Try to restore:
        │         1. Create SoCo(coordinator_ip)
        │         2. For each member_ip in saved_members:
        │              member = SoCo(member_ip)
        │              member.join(coordinator)
        │         3. Re-scan group to verify
        │              │
        │         Success ──► Update saved uid, play
        │              │
        │         Fail ─────► Log warning, play on whatever
        │                      group the configured IP is in
        │
        No ──────► No saved group — play normally
                   (single speaker or whatever group exists)
```

## Sample Code

### 1. Settings router — add new fields

`routers/settings.py`:

```python
DEFAULTS = {
    "sonos_ip":              "10.0.1.90",
    "sonos_group_coordinator": "",       # NEW
    "sonos_group_members":     "",       # NEW — JSON string
    # ... existing fields
}

class SettingsUpdate(BaseModel):
    sonos_ip:                    Optional[str] = None
    sonos_group_coordinator:     Optional[str] = None   # NEW
    sonos_group_members:         Optional[str] = None   # NEW
    # ... existing fields
```

### 2. Sonos controller — group functions

`services/sonos_controller.py`:

```python
import json


def get_current_group(sonos_ip: str) -> dict:
    """
    Return info about the group the configured speaker is currently in.
    Returns empty dict if solo.
    """
    player = _player(sonos_ip)
    try:
        group = player.group
        if group is None:
            return {}
        member_ips = [m.speaker_ip for m in group.members]
        return {
            "uid":        group.uid,
            "coordinator": group.coordinator.speaker_ip,
            "members":    member_ips,
        }
    except Exception as e:
        return {"error": str(e)}


def save_group(sonos_ip: str) -> dict:
    """
    Scan the current group and save coordinator + members to settings.
    """
    from routers.settings import get_settings, DEFAULTS

    player = _player(sonos_ip)
    group = player.group
    if group is None:
        return {"status": "skipped", "message": "Speaker is solo — no group to save"}

    coordinator_ip = group.coordinator.speaker_ip
    member_ips = [m.speaker_ip for m in group.members]

    settings = get_settings()
    settings["sonos_group_coordinator"] = coordinator_ip
    settings["sonos_group_members"] = json.dumps(member_ips)

    # Persist to DB via the settings router
    from routers.settings import update_settings
    from pydantic import BaseModel
    class GroupSettingsUpdate(BaseModel):
        sonos_group_coordinator: Optional[str] = None
        sonos_group_members: Optional[str] = None
    update_settings(GroupSettingsUpdate(
        sonos_group_coordinator=coordinator_ip,
        sonos_group_members=json.dumps(member_ips),
    ))

    return {
        "status": "saved",
        "coordinator": coordinator_ip,
        "members": member_ips,
        "uid": group.uid,
    }


def restore_group(sonos_ip: str) -> dict:
    """
    If the configured speaker is not in its saved group, attempt to
    rejoin all saved members to the saved coordinator.
    Returns info about what happened.
    """
    from routers.settings import get_settings

    settings = get_settings()
    saved_coordinator = settings.get("sonos_group_coordinator", "")
    saved_members_str = settings.get("sonos_group_members", "")

    if not saved_coordinator or not saved_members_str:
        return {"status": "no-group-configured", "message": "No saved group found"}

    saved_members = json.loads(saved_members_str)

    # Check if we're already in the right group
    player = _player(sonos_ip)
    current_group = get_current_group(sonos_ip)

    if current_group:
        # Verify the coordinator matches
        if current_group["coordinator"] == saved_coordinator:
            # Check if all saved members are present
            saved_set = set(saved_members)
            current_set = set(current_group["members"])
            if saved_set == current_set:
                return {
                    "status": "already-restored",
                    "group": current_group,
                }

    # Group is broken or changed — attempt restore
    coordinator = _player(saved_coordinator)
    restored = []
    failed = []

    for member_ip in saved_members:
        if member_ip == saved_coordinator:
            restored.append(member_ip)
            continue
        try:
            member = _player(member_ip)
            member.join(coordinator)
            restored.append(member_ip)
        except Exception as e:
            failed.append({"ip": member_ip, "error": str(e)})

    # Re-scan to verify
    new_group = get_current_group(sonos_ip)

    if failed:
        return {
            "status": "partial",
            "restored": restored,
            "failed": failed,
            "current_group": new_group,
        }

    if new_group:
        return {
            "status": "restored",
            "group": new_group,
        }

    return {
        "status": "failed",
        "message": "Could not restore group — coordinator may be offline",
        "restored": restored,
        "failed": failed,
    }


def ensure_group(sonos_ip: str) -> dict:
    """
    Public entry point: check if group exists, restore if needed.
    Call this before any play operation.
    """
    result = restore_group(sonos_ip)
    if result["status"] in ("no-group-configured", "already-restored"):
        return {"status": "ok", **result}
    return result
```

### 3. Router endpoints

`routers/sonos.py`:

```python
class SaveGroupRequest(BaseModel):
    pass  # uses configured sonos_ip


@router.get("/group")
async def get_group():
    """Get current group info for the configured speaker."""
    sonos_ip = _get_sonos_ip()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.get_current_group, sonos_ip)


@router.post("/save-group")
async def save_group_endpoint():
    """Save the current group to settings."""
    sonos_ip = _get_sonos_ip()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.save_group, sonos_ip)


@router.get("/restore-group")
async def restore_group_endpoint():
    """Check and restore saved group if broken."""
    sonos_ip = _get_sonos_ip()
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.ensure_group, sonos_ip)
```

### 4. Call restore before playing

`routers/sonos.py` — modify `play_file` and `play_folder`:

```python
@router.post("/play-file")
async def play_file(req: PlayFileRequest):
    """Play a single music file on Sonos."""
    sonos_ip = _get_sonos_ip()

    # Ensure group is restored before playing
    loop = asyncio.get_event_loop()
    group_result = await loop.run_in_executor(None, sc.ensure_group, sonos_ip)
    if group_result.get("status") == "failed":
        return {
            "status": "warning",
            "message": f"Could not restore group: {group_result.get('message')}",
        }

    uri      = _build_url(req.path)
    title    = req.name or req.path.split('/')[-1]
    result   = await loop.run_in_executor(None, sc.play_uri, sonos_ip, uri, title)
    return {**result, "title": title, "proxy_url": uri, "group": group_result}
```

### 5. Frontend — group status display

`static/app.js` — add to the playbar or expanded player:

```javascript
// After syncSonosState, also check group status
async function syncSonosState() {
    // ... existing state sync ...

    // Check group integrity
    try {
        const grpRes = await fetch('/api/sonos/group');
        const grp = await grpRes.json();
        if (grp.error) {
            showGroupStatus('error', 'Group error: ' + grp.error);
        } else if (!grp.uid) {
            showGroupStatus('solo', 'Solo speaker');
        } else {
            showGroupStatus('ok', grp.members.length + ' speakers');
        }
    } catch {}
}

function showGroupStatus(type, text) {
    let el = document.getElementById('group-status');
    if (!el) {
        el = document.createElement('span');
        el.id = 'group-status';
        el.className = 'group-status';
        playbar?.insertBefore(el, volumeSlider);
    }
    el.textContent = text;
    el.className = 'group-status group-' + type;
}
```

### 6. Frontend — save group button

Add to the Settings tab or as a button in the expanded player:

```html
<!-- In settings tab -->
<button id="save-group-btn" class="btn-primary">Save Current Group</button>
```

```javascript
// In app.js
document.getElementById('save-group-btn')?.addEventListener('click', async () => {
    const res = await fetch('/api/sonos/save-group', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'saved') {
        showToast(`Group saved: ${data.members.length} speakers`, 'success');
    } else {
        showToast(data.message, 'warning');
    }
});
```

## Edge Cases & Considerations

### Coordinator goes offline
- `member.join(coordinator)` will raise an exception → caught by `restore_group()`, reported as partial/failed
- App falls back to playing on whatever group the configured IP belongs to
- The user should manually save the new group after the coordinator comes back or a new one is elected

### Speaker physically removed from the network
- `join()` will fail for that speaker → reported in `failed` list
- All other speakers rejoin successfully
- Next time the removed speaker comes back, it'll be solo (not in the group)
- User needs to either manually rejoin it or save a new group config

### Stereo pair
- `player.group` returns `None` for the slave speaker
- The master speaker's `player.group` returns the full group
- `save_group()` should be called from the master's IP to capture the correct group
- Volume already works correctly via `group.volume`

### Group changes while app is running
- The poller could periodically call `restore_group()` to detect drift
- Or we could just check on each play attempt (simpler, less overhead)
- Consider adding a "refresh group" button so the user can update the saved config

### Multiple groups on the network
- The app only knows about one group (the one tied to `sonos_ip`)
- If the user has multiple Sonos groups and wants to control different ones,
  that would require a more complex multi-player architecture (beyond current scope)

## Implementation Order

1. **Add settings fields** — `sonos_group_coordinator`, `sonos_group_members`
2. **Add `get_current_group()`** — simple read-only function
3. **Add `/api/sonos/group` endpoint** — let the UI see group status
4. **Add `save_group()` + `/api/sonos/save-group`** — let user capture current group
5. **Add `restore_group()` + `/api/sonos/restore-group`** — the core restoration logic
6. **Wire restore into `play_file`/`play_folder`** — auto-restore before playing
7. **Add UI** — group status badge in playbar, save-group button in settings
