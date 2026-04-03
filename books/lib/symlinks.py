import os
import re

from .config import BY_AUTHOR_DIR_NAME, BY_YEAR_DIR_NAME, COLLECTIONS_DIR_NAME
from .util import clean_asin, extract_authors


def update_author_symlinks(real_file_path, library_root):
    """Creates symlinks in the 'By Author' directory."""
    filename = os.path.basename(real_file_path)
    authors = extract_authors(filename)

    if not authors:
        return

    base_author_dir = os.path.join(library_root, BY_AUTHOR_DIR_NAME)

    for author in authors:
        author_dir = os.path.join(base_author_dir, author)
        os.makedirs(author_dir, exist_ok=True)

        link_path = os.path.join(author_dir, filename)

        real_file_abs = os.path.abspath(real_file_path)
        link_dir_abs = os.path.dirname(os.path.abspath(link_path))
        target_path = os.path.relpath(real_file_abs, start=link_dir_abs)

        if os.path.exists(link_path) or os.path.islink(link_path):
            try:
                os.unlink(link_path)
            except OSError:
                pass

        try:
            os.symlink(target_path, link_path)
        except OSError as e:
            print(f"[WARN] Could not create symlink for {author}: {e}")


def update_year_symlinks(real_file_path, library_root, meta_map):
    """Creates symlinks in the 'By Year' directory."""
    filename = os.path.basename(real_file_path)

    regex_asin = re.compile(r'\[([A-Z0-9]+)\]')
    match = regex_asin.search(filename)
    if not match:
        return

    asin = clean_asin(match.group(1))
    if asin not in meta_map:
        return

    year = meta_map[asin].get('year')
    if not year:
        return

    if not re.match(r'^\d{4}$', year):
        return

    try:
        y_int = int(year)
        decade_start = (y_int // 10) * 10
        decade_str = f"{decade_start}s"
    except ValueError:
        return

    base_year_dir = os.path.join(library_root, BY_YEAR_DIR_NAME)

    year_dir = os.path.join(base_year_dir, decade_str, year)
    os.makedirs(year_dir, exist_ok=True)

    link_path = os.path.join(year_dir, filename)

    real_file_abs = os.path.abspath(real_file_path)
    link_dir_abs = os.path.dirname(os.path.abspath(link_path))
    target_path = os.path.relpath(real_file_abs, start=link_dir_abs)

    if os.path.exists(link_path) or os.path.islink(link_path):
        try:
            os.unlink(link_path)
        except OSError:
            pass

    try:
        os.symlink(target_path, link_path)
    except OSError as e:
        print(f"[WARN] Could not create symlink for {year}: {e}")


def update_collection_symlinks(real_file_path, library_root, collection_index):
    """Creates symlinks in the 'Collections' directory."""
    if not collection_index:
        return

    filename = os.path.basename(real_file_path)
    regex_asin = re.compile(r'\[([A-Z0-9]+)\]')
    match = regex_asin.search(filename)
    if not match:
        return

    asin = clean_asin(match.group(1))
    if asin not in collection_index:
        return

    base_collections_dir = os.path.join(library_root, COLLECTIONS_DIR_NAME)

    for collection_name in sorted(collection_index[asin]):
        collection_dir = os.path.join(base_collections_dir, collection_name)
        os.makedirs(collection_dir, exist_ok=True)

        link_path = os.path.join(collection_dir, filename)

        real_file_abs = os.path.abspath(real_file_path)
        link_dir_abs = os.path.dirname(os.path.abspath(link_path))
        target_path = os.path.relpath(real_file_abs, start=link_dir_abs)

        if os.path.exists(link_path) or os.path.islink(link_path):
            try:
                os.unlink(link_path)
            except OSError:
                pass

        try:
            os.symlink(target_path, link_path)
        except OSError as e:
            print(f"[WARN] Could not create symlink for collection '{collection_name}': {e}")
