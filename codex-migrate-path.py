#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
from typing import Any


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate local Codex metadata from one path to another.",
        epilog="The workspace directories themselves are not renamed.",
    )
    parser.add_argument(
        "old_path",
        metavar="OLD_PATH",
        help="existing path recorded by Codex",
    )
    parser.add_argument(
        "new_path",
        metavar="NEW_PATH",
        help="replacement path to record in Codex metadata",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(
            os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        ),
        metavar="DIR",
        help="Codex data directory (defaults to CODEX_HOME or ~/.codex)",
    )
    return parser.parse_args()


arguments = parse_arguments()
old_path = os.path.normpath(arguments.old_path)
new_path = os.path.normpath(arguments.new_path)
codex_home = arguments.codex_home.expanduser()
state_db = codex_home / "state_5.sqlite"
config_path = codex_home / "config.toml"
sessions_dir = codex_home / "sessions"


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def migrated_path(path: str) -> str | None:
    if path == old_path:
        return new_path
    prefix = old_path + os.sep
    if path.startswith(prefix):
        return new_path + path[len(old_path) :]
    return None


def read_session_metadata(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as session_file:
            first_line = session_file.readline()
        if not first_line:
            return None
        record = json.loads(first_line)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    if record.get("type") != "session_meta":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("cwd"), str):
        return None

    return {
        "id": payload.get("id") or payload.get("session_id"),
        "cwd": payload["cwd"],
        "path": path,
    }


def running_codex_processes() -> list[str]:
    processes: list[str] = []
    for process_name in ("codex", "codex-code-mode-host"):
        try:
            result = subprocess.run(
                ["pgrep", "-x", process_name],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            return ["unable to inspect running processes"]

        for pid in result.stdout.split():
            try:
                details = subprocess.run(
                    ["ps", "-o", "pid=,args=", "-p", pid],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError:
                processes.append(f"pid {pid}")
                continue
            processes.append(details.stdout.strip() or f"pid {pid}")
    return processes


def project_header(path: str) -> str:
    return f'[projects."{path}"]'


def display_title(title: Any) -> str:
    compact_title = " ".join(str(title).split())
    if len(compact_title) > 200:
        return compact_title[:197] + "..."
    return compact_title


def migrate_config(config_text: str) -> tuple[str, bool, bool]:
    old_header = project_header(old_path)
    new_header = project_header(new_path)
    lines = config_text.splitlines(keepends=True)
    old_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == old_header
    ]
    new_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == new_header
    ]

    if len(old_indexes) > 1 or len(new_indexes) > 1:
        fail(f"found duplicate project entries in {config_path}")
    if old_indexes and new_indexes:
        fail(
            f"both project entries already exist in {config_path}; "
            "merge their settings manually"
        )
    if not old_indexes:
        return config_text, False, bool(new_indexes)

    lines[old_indexes[0]] = lines[old_indexes[0]].replace(old_header, new_header, 1)
    return "".join(lines), True, False


def atomic_write(path: Path, content: bytes) -> None:
    original_mode = stat.S_IMODE(path.stat().st_mode)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def update_session_metadata(path: Path, current_cwd: str) -> None:
    content = path.read_bytes()
    first_line, separator, remainder = content.partition(b"\n")
    record = json.loads(first_line.decode("utf-8"))
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("cwd") != current_cwd:
        fail(f"session metadata changed unexpectedly: {path}")

    replacement_cwd = migrated_path(current_cwd)
    if replacement_cwd is None:
        fail(f"session metadata no longer matches the requested path: {path}")

    encoded_current = json.dumps(
        current_cwd, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    encoded_replacement = json.dumps(
        replacement_cwd, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    pattern = re.compile(rb'("cwd"\s*:\s*)' + re.escape(encoded_current))
    updated_first_line, replacements = pattern.subn(
        lambda match: match.group(1) + encoded_replacement,
        first_line,
        count=1,
    )
    if replacements != 1:
        fail(f"could not locate the session cwd field: {path}")

    atomic_write(path, updated_first_line + separator + remainder)


def backup_sqlite(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()
    finally:
        destination_connection.close()
        source_connection.close()
    os.chmod(destination, stat.S_IMODE(source.stat().st_mode))


if not old_path.startswith("/") or not new_path.startswith("/"):
    fail("both paths must be absolute")
if old_path in ("", os.sep) or new_path in ("", os.sep):
    fail("a filesystem root cannot be migrated")
if old_path == new_path:
    fail("the old and new paths are identical")
if new_path.startswith(old_path + os.sep):
    fail("the new path cannot be inside the old path")
for label, path in (("old", old_path), ("new", new_path)):
    if any(character in path for character in '\r\n"\\'):
        fail(f"the {label} path contains a character unsupported by config.toml")

if not state_db.is_file():
    fail(f"Codex state database not found: {state_db}")
if not config_path.is_file():
    fail(f"Codex config not found: {config_path}")

try:
    config_text = config_path.read_text(encoding="utf-8")
except (OSError, UnicodeError) as error:
    fail(f"cannot read {config_path}: {error}")
updated_config, config_needs_update, destination_config_exists = migrate_config(
    config_text
)

try:
    database_connection = sqlite3.connect(state_db)
    database_connection.row_factory = sqlite3.Row
    try:
        thread_rows = list(
            database_connection.execute(
                "SELECT id, cwd, title, rollout_path FROM threads"
            )
        )
        project_root_rows = []
        project_roots_table = database_connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'project_roots'"
        ).fetchone()
        if project_roots_table is not None:
            project_root_rows = list(
                database_connection.execute(
                    "SELECT project_id, position, path FROM project_roots"
                )
            )
    finally:
        database_connection.close()
except sqlite3.Error as error:
    fail(f"cannot inspect {state_db}: {error}")

matching_threads: list[dict[str, Any]] = []
for row in thread_rows:
    current_cwd = row["cwd"]
    if isinstance(current_cwd, str) and migrated_path(current_cwd) is not None:
        matching_threads.append(
            {
                "id": row["id"],
                "cwd": current_cwd,
                "title": row["title"] or "(untitled)",
                "rollout_path": row["rollout_path"] or "",
            }
        )

matching_project_roots: list[dict[str, Any]] = []
for row in project_root_rows:
    current_path = row["path"]
    if isinstance(current_path, str) and migrated_path(current_path) is not None:
        matching_project_roots.append(
            {
                "project_id": row["project_id"],
                "position": row["position"],
                "path": current_path,
            }
        )

sessions_by_id: dict[str, dict[str, Any]] = {
    session["id"]: session
    for session in matching_threads
    if isinstance(session["id"], str) and session["id"]
}
metadata_files: dict[Path, dict[str, Any]] = {}
if sessions_dir.is_dir():
    for candidate in sessions_dir.rglob("rollout-*.jsonl"):
        metadata = read_session_metadata(candidate)
        if metadata is None or migrated_path(metadata["cwd"]) is None:
            continue
        metadata_files[candidate] = metadata
        session_id = metadata.get("id")
        if isinstance(session_id, str) and session_id:
            session = sessions_by_id.setdefault(
                session_id,
                {
                    "id": session_id,
                    "cwd": metadata["cwd"],
                    "title": "(title unavailable)",
                    "rollout_path": str(candidate),
                },
            )
            session["metadata_path"] = candidate

for session in matching_threads:
    rollout_path = session.get("rollout_path")
    if rollout_path:
        candidate = Path(rollout_path)
        if not candidate.is_absolute():
            candidate = codex_home / candidate
        if candidate in metadata_files:
            session["metadata_path"] = candidate

sessions = sorted(
    sessions_by_id.values(),
    key=lambda session: (str(session.get("cwd", "")), str(session.get("id", ""))),
)

print(f"Codex path migration: {old_path} -> {new_path}")
print(f"Matching saved sessions: {len(sessions)}")
for session in sessions:
    current_cwd = session.get("cwd", "")
    print(f"  {session.get('id', '(unknown id)')}")
    print(f"    cwd: {current_cwd} -> {migrated_path(current_cwd)}")
    print(f"    title: {display_title(session.get('title', '(untitled)'))}")
    rollout_path = session.get("rollout_path") or session.get("metadata_path")
    print(f"    rollout: {rollout_path or '(not recorded in the thread index)'}")
if not sessions:
    print("  (none)")
print(f"Thread records to update: {len(matching_threads)}")
print(f"Project root records to update: {len(matching_project_roots)}")
print(f"Rollout metadata files to update: {len(metadata_files)}")
if config_needs_update:
    print(f"Project config entry to update: {config_path}")
elif destination_config_exists:
    print(f"Project config entry already uses the new path: {config_path}")
else:
    print(f"Project config entry for the old path: (not present in {config_path})")
print("The workspace directories themselves will not be renamed.")
print("Codex must be fully closed before the changes are applied.")

try:
    answer = input("Proceed with this Codex metadata migration? [y/N] ")
except EOFError:
    answer = ""
if answer.strip().lower() not in {"y", "yes"}:
    print("No changes made.")
    raise SystemExit(0)

running_processes = running_codex_processes()
if running_processes:
    print("error: Codex is still running; no changes were made:", file=sys.stderr)
    for process in running_processes:
        print(f"  {process}", file=sys.stderr)
    raise SystemExit(1)

timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%SZ")
destination_leaf = new_path.rsplit(os.sep, 1)[-1]
backup_tag = f"{timestamp}.before-{destination_leaf}"
database_backup = state_db.with_name(f"{state_db.name}.{backup_tag}")
config_backup = config_path.with_name(f"{config_path.name}.{backup_tag}")
metadata_backups: dict[Path, Path] = {
    path: Path(f"{path}.{backup_tag}") for path in metadata_files
}

backup_paths = [database_backup]
if config_needs_update:
    backup_paths.append(config_backup)
backup_paths.extend(metadata_backups.values())
existing_backups = [path for path in backup_paths if path.exists()]
if existing_backups:
    fail(
        "refusing to overwrite existing backup(s): "
        + ", ".join(str(path) for path in existing_backups)
    )

changed_files: list[tuple[Path, Path]] = []
try:
    backup_sqlite(state_db, database_backup)

    if config_needs_update:
        shutil.copy2(config_path, config_backup)
        atomic_write(config_path, updated_config.encode("utf-8"))
        changed_files.append((config_path, config_backup))

    for metadata_path, backup_path in metadata_backups.items():
        shutil.copy2(metadata_path, backup_path)
        current_cwd = metadata_files[metadata_path]["cwd"]
        update_session_metadata(metadata_path, current_cwd)
        changed_files.append((metadata_path, backup_path))

    database_connection = sqlite3.connect(state_db)
    try:
        database_connection.execute("BEGIN IMMEDIATE")
        updated_threads = 0
        for session in matching_threads:
            replacement_cwd = migrated_path(session["cwd"])
            cursor = database_connection.execute(
                "UPDATE threads SET cwd = ? WHERE id = ? AND cwd = ?",
                (replacement_cwd, session["id"], session["cwd"]),
            )
            updated_threads += cursor.rowcount
        updated_project_roots = 0
        for project_root in matching_project_roots:
            replacement_path = migrated_path(project_root["path"])
            cursor = database_connection.execute(
                "UPDATE project_roots SET path = ? "
                "WHERE project_id = ? AND position = ? AND path = ?",
                (
                    replacement_path,
                    project_root["project_id"],
                    project_root["position"],
                    project_root["path"],
                ),
            )
            updated_project_roots += cursor.rowcount
        if updated_threads != len(matching_threads) or updated_project_roots != len(
            matching_project_roots
        ):
            raise RuntimeError(
                "the Codex state index changed while the migration was running"
            )
        database_connection.commit()
    except Exception:
        database_connection.rollback()
        raise
    finally:
        database_connection.close()
except Exception as error:
    for original_path, backup_path in reversed(changed_files):
        try:
            shutil.copy2(backup_path, original_path)
        except OSError as rollback_error:
            print(
                f"error: rollback failed for {original_path}: {rollback_error}",
                file=sys.stderr,
            )
    fail(f"migration failed; state database backup is {database_backup}: {error}")

print("Migration completed.")
print(f"State database backup: {database_backup}")
if config_needs_update:
    print(f"Config backup: {config_backup}")
for backup_path in metadata_backups.values():
    print(f"Rollout backup: {backup_path}")
