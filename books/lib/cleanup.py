import os
import shutil
import time

from .config import BY_AUTHOR_DIR_NAME, BY_YEAR_DIR_NAME, COLLECTIONS_DIR_NAME


def remove_empty_dirs(path, dry_run):
    if not os.path.isdir(path):
        return
    for root, dirs, files in os.walk(path, topdown=False):
        for name in dirs:
            if name == BY_AUTHOR_DIR_NAME:
                continue
            if name == BY_YEAR_DIR_NAME:
                continue
            if name == COLLECTIONS_DIR_NAME:
                continue

            full_path = os.path.join(root, name)
            try:
                if not os.listdir(full_path):
                    if dry_run:
                        print(f"[DELETE] Empty Folder: {name}")
                    else:
                        os.rmdir(full_path)
            except OSError:
                pass


def reset_author_dir(library_root, dry_run):
    """Wipes the 'By Author' directory to ensure a clean rebuild of links."""
    author_path = os.path.join(library_root, BY_AUTHOR_DIR_NAME)

    if os.path.exists(author_path):
        if dry_run:
            print(f"[RESET] Would delete and recreate '{BY_AUTHOR_DIR_NAME}'")
        else:
            trash_name = f"{BY_AUTHOR_DIR_NAME}_trash_{int(time.time())}"
            trash_path = os.path.join(library_root, trash_name)

            try:
                os.rename(author_path, trash_path)
            except OSError as e:
                print(f"[WARN] Could not rename old author dir: {e}. Attempting direct delete.")
                shutil.rmtree(author_path, ignore_errors=True)
                trash_path = None

            os.makedirs(author_path, exist_ok=True)

            if trash_path and os.path.exists(trash_path):
                try:
                    shutil.rmtree(trash_path)
                except OSError as e:
                    print(f"[WARN] Failed to fully clean up trash dir {trash_path}: {e}")
    else:
        if not dry_run:
            os.makedirs(author_path)


def reset_year_dir(library_root, dry_run):
    """Wipes the 'By Year' directory."""
    year_path = os.path.join(library_root, BY_YEAR_DIR_NAME)

    if os.path.exists(year_path):
        if dry_run:
            print(f"[RESET] Would delete and recreate '{BY_YEAR_DIR_NAME}'")
        else:
            trash_name = f"{BY_YEAR_DIR_NAME}_trash_{int(time.time())}"
            trash_path = os.path.join(library_root, trash_name)

            try:
                os.rename(year_path, trash_path)
            except OSError:
                shutil.rmtree(year_path, ignore_errors=True)
                trash_path = None

            os.makedirs(year_path, exist_ok=True)

            if trash_path and os.path.exists(trash_path):
                try:
                    shutil.rmtree(trash_path)
                except OSError:
                    pass
    else:
        if not dry_run:
            os.makedirs(year_path)


def reset_collections_dir(library_root, dry_run):
    """Wipes the 'Collections' directory."""
    collections_path = os.path.join(library_root, COLLECTIONS_DIR_NAME)

    if os.path.exists(collections_path):
        if dry_run:
            print(f"[RESET] Would delete and recreate '{COLLECTIONS_DIR_NAME}'")
        else:
            trash_name = f"{COLLECTIONS_DIR_NAME}_trash_{int(time.time())}"
            trash_path = os.path.join(library_root, trash_name)

            try:
                os.rename(collections_path, trash_path)
            except OSError:
                shutil.rmtree(collections_path, ignore_errors=True)
                trash_path = None

            os.makedirs(collections_path, exist_ok=True)

            if trash_path and os.path.exists(trash_path):
                try:
                    shutil.rmtree(trash_path)
                except OSError:
                    pass
    else:
        if not dry_run:
            os.makedirs(collections_path)
