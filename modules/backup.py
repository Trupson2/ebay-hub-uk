"""
eBay Hub UK — Auto-backup system
Hourly backups with integrity verification, keeps 48 latest.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).parent.parent
DB_PATH = APP_DIR / 'ebay_hub.db'
BACKUP_DIR = APP_DIR / 'backups'
MAX_BACKUPS = 48  # Keep 48 backups (2 days at hourly)
BACKUP_INTERVAL = 3600  # 1 hour


def ensure_backup_dir():
    BACKUP_DIR.mkdir(exist_ok=True)
    return BACKUP_DIR


def create_backup():
    """Create a verified backup of the database."""
    try:
        ensure_backup_dir()
        if not DB_PATH.exists():
            print(f"[BACKUP] DB not found: {DB_PATH}")
            return None

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"ebay_hub_backup_{timestamp}.db"
        backup_path = BACKUP_DIR / backup_name

        # Use SQLite backup API (safe, even during writes)
        source = sqlite3.connect(str(DB_PATH))
        dest = sqlite3.connect(str(backup_path))
        with dest:
            source.backup(dest)
        source.close()
        dest.close()

        # Verify integrity
        verify = sqlite3.connect(str(backup_path))
        result = verify.execute('PRAGMA integrity_check').fetchone()
        verify.close()

        if result[0] != 'ok':
            print(f"[BACKUP] Corrupted! Deleting: {backup_name}")
            backup_path.unlink(missing_ok=True)
            return None

        print(f"[BACKUP] Created: {backup_name}")
        cleanup_old_backups()
        return backup_path

    except Exception as e:
        print(f"[BACKUP] Error: {e}")
        return None


def cleanup_old_backups():
    """Remove old backups, keep MAX_BACKUPS newest."""
    try:
        backups = sorted(BACKUP_DIR.glob('ebay_hub_backup_*.db'), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[MAX_BACKUPS:]:
            old.unlink()
            print(f"[BACKUP] Removed old: {old.name}")
    except Exception as e:
        print(f"[BACKUP] Cleanup error: {e}")


def get_backups():
    """List available backups."""
    ensure_backup_dir()
    backups = []
    for f in sorted(BACKUP_DIR.glob('ebay_hub_backup_*.db'), key=lambda p: p.stat().st_mtime, reverse=True):
        size_mb = f.stat().st_size / (1024 * 1024)
        backups.append({
            'name': f.name,
            'path': str(f),
            'size_mb': round(size_mb, 2),
            'date': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
        })
    return backups


def restore_backup(backup_name):
    """Restore database from a backup."""
    backup_path = BACKUP_DIR / backup_name
    if not backup_path.exists():
        return False, "Backup not found"

    try:
        # Verify backup first
        verify = sqlite3.connect(str(backup_path))
        result = verify.execute('PRAGMA integrity_check').fetchone()
        verify.close()
        if result[0] != 'ok':
            return False, "Backup is corrupted"

        # Create safety backup of current DB
        create_backup()

        # Replace current DB
        import shutil
        shutil.copy2(str(backup_path), str(DB_PATH))
        return True, f"Restored from {backup_name}"

    except Exception as e:
        return False, str(e)


def start_backup_scheduler():
    """Start hourly backup thread."""
    def _loop():
        # Wait 5 minutes after startup
        time.sleep(300)
        while True:
            try:
                create_backup()
            except Exception as e:
                print(f"[BACKUP] Scheduler error: {e}")
            time.sleep(BACKUP_INTERVAL)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("[BACKUP] Hourly backup scheduler started")
    return t
