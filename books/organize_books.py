#!/usr/bin/env python

# To create a folder of test files matching the filenames of a directory of books:
#   find path/to/books -type f -exec bash -c 'echo "$1" > "test/$(basename "$1")"' -- {} \;

import json
import os
import shutil
import re
import argparse
from collections import defaultdict
import time

# --- CONFIGURATION ---
BY_AUTHOR_DIR_NAME = "By Author"
BY_YEAR_DIR_NAME = "By Year"

# --- CLASSES ---

class LibraryNode:
    def __init__(self, folder_name, full_path):
        self.folder_name = folder_name
        self.full_path = full_path
        self.files = []
        self.children = {}
        self.ddc_def = None

    def add_file(self, file_info):
        self.files.append(file_info)

# --- UTILITIES ---

def clean_asin(ident):
    if not ident: return ""
    return str(ident).replace('-', '').replace(' ', '').strip()

def get_folder_name(node_def):
    """Format: 'ID Description'"""
    desc = node_def.get('description', 'Unknown').replace('/', '-')
    node_id = node_def.get('id', '???')
    return f"{node_id} {desc}"

def extract_authors(filename):
    """
    Parses 'Title by Author1, Author2, and Author3 [ASIN].pdf'
    Returns a list of author names: ['Author1', 'Author2', 'Author3']
    """
    # Regex to capture text between " by " and " ["
    # We use greedy matching (.*) at the start to find the LAST " by "
    match = re.search(r'.* by (.+?) \[', filename)
    if not match:
        return []

    raw_author_str = match.group(1)

    # 1. Normalization: Replace " and " with a comma, and handle "and" at start of names
    # Strategy: Split by comma first, then check the last chunk for "and"

    # Simple strategy: Replace ", and " -> "," AND " and " -> ","
    # This covers "A, B, and C" -> "A, B, C"
    # This covers "A and B" -> "A, B"
    clean_str = raw_author_str.replace(", and ", ",").replace(" and ", ",")

    authors = []
    for a in clean_str.split(','):
        # Remove parenthesized text (e.g. " (Editor)")
        a_clean = re.sub(r'\(.*?\)', '', a).strip()
        if a_clean:
            authors.append(a_clean)
    return authors

def update_author_symlinks(real_file_path, library_root):
    """Creates symlinks in the 'By Author' directory."""
    filename = os.path.basename(real_file_path)
    authors = extract_authors(filename)

    if not authors:
        return

    base_author_dir = os.path.join(library_root, BY_AUTHOR_DIR_NAME)

    for author in authors:
        # Create author specific directory
        author_dir = os.path.join(base_author_dir, author)
        os.makedirs(author_dir, exist_ok=True)

        link_path = os.path.join(author_dir, filename)

        # Determine target path (Relative paths for portability)
        # We need the path from the LINK LOCATION to the REAL FILE
        real_file_abs = os.path.abspath(real_file_path)
        link_dir_abs = os.path.dirname(os.path.abspath(link_path))
        target_path = os.path.relpath(real_file_abs, start=link_dir_abs)

        # Remove existing link if it exists (to update location)
        if os.path.exists(link_path) or os.path.islink(link_path):
            try:
                os.unlink(link_path)
            except OSError:
                pass

        try:
            os.symlink(target_path, link_path)
        except OSError as e:
            # Common on Windows if not running as Admin/Dev Mode
            print(f"[WARN] Could not create symlink for {author}: {e}")

def update_year_symlinks(real_file_path, library_root, meta_map):
    """Creates symlinks in the 'By Year' directory."""
    filename = os.path.basename(real_file_path)

    # Extract ASIN to lookup year
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

    # Validate year (simple 4 digit check)
    if not re.match(r'^\d{4}$', year):
        return

    # Determine Decade
    try:
        y_int = int(year)
        decade_start = (y_int // 10) * 10
        decade_str = f"{decade_start}s"
    except ValueError:
        return

    base_year_dir = os.path.join(library_root, BY_YEAR_DIR_NAME)

    # Structure: By Year / 1980s / 1984 / filename
    year_dir = os.path.join(base_year_dir, decade_str, year)
    os.makedirs(year_dir, exist_ok=True)

    link_path = os.path.join(year_dir, filename)

    # Determine target path (Relative paths)
    real_file_abs = os.path.abspath(real_file_path)
    link_dir_abs = os.path.dirname(os.path.abspath(link_path))
    target_path = os.path.relpath(real_file_abs, start=link_dir_abs)

    # Remove existing link
    if os.path.exists(link_path) or os.path.islink(link_path):
        try:
            os.unlink(link_path)
        except OSError:
            pass

    try:
        os.symlink(target_path, link_path)
    except OSError as e:
        print(f"[WARN] Could not create symlink for {year}: {e}")

# --- LOADERS ---

def load_json_map(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: {path} is corrupted. Starting empty.")
    return {}

def save_json_map(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, sort_keys=True)
        print(f"Successfully saved manual map to: {path}")
    except IOError as e:
        print(f"Error saving manual map: {e}")

def load_lt_metadata(lt_path):
    print(f"Loading Metadata: {lt_path}...")
    try:
        with open(lt_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Metadata file {lt_path} not found.")
        return {}

    meta_map = {}
    for book in data.values():
        val_map = {}

        # 1. DDC
        if 'ddc' in book and 'code' in book['ddc']:
            raw = book['ddc']['code']
            ddc_code = raw[0] if isinstance(raw, list) else raw
            val_map['ddc'] = str(ddc_code).strip()

        # 2. Year (Date)
        if 'date' in book:
             val_map['year'] = str(book['date']).strip()

        if not val_map: continue

        ids = set()
        if 'asin' in book: ids.add(clean_asin(book['asin']))
        if 'isbn' in book and isinstance(book['isbn'], dict):
            for v in book['isbn'].values(): ids.add(clean_asin(v))

        for i in ids:
            if i: meta_map[i] = val_map

    return meta_map

def load_ddc_index(index_path):
    print(f"Loading DDC Map: {index_path}...")
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict): return [data]
            return data
    except FileNotFoundError:
        print(f"Error: DDC Map file {index_path} not found.")
        return []

# --- CORE LOGIC ---

def parse_ddc_num(num_str):
    try:
        return float(str(num_str).strip())
    except ValueError:
        return 0.0

def resolve_path_stack(ddc_code, ddc_tree):
    if not ddc_code: return []

    target_val = parse_ddc_num(ddc_code)
    path_definitions = []

    current_candidates = ddc_tree

    while current_candidates:
        best_node = None

        valid_nodes = [n for n in current_candidates if 'number' in n]
        valid_nodes.sort(key=lambda x: parse_ddc_num(x['number']))

        for i, node in enumerate(valid_nodes):
            node_val = parse_ddc_num(node['number'])

            if node_val <= target_val:
                is_last = (i == len(valid_nodes) - 1)
                if is_last:
                    best_node = node
                else:
                    next_val = parse_ddc_num(valid_nodes[i+1]['number'])
                    if target_val < next_val:
                        best_node = node
                        break
            else:
                break

        if best_node:
            path_definitions.append(best_node)
            current_candidates = best_node.get('subordinates', [])
        else:
            break

    return path_definitions

def build_virtual_tree(files, meta_map, manual_map, ddc_tree, library_root):
    root = LibraryNode("ROOT", library_root)
    regex_asin = re.compile(r'\[([A-Z0-9]+)\]')
    map_updated = False

    print(f"Processing {len(files)} files...")

    for src_path in files:
        filename = os.path.basename(src_path)

        match = regex_asin.search(filename)
        ddc_code = None

        # 1. Metadata Lookup
        if match:
            asin = clean_asin(match.group(1))
            if asin in meta_map:
                ddc_code = meta_map[asin].get('ddc')

        # 2. Manual Map Lookup
        if not ddc_code:
            if filename in manual_map:
                ddc_code = manual_map[filename]
            else:
                print(f"[NEW] Tracking unknown file: {filename}")
                manual_map[filename] = None
                map_updated = True

        # 3. Build Tree
        if ddc_code:
            path_stack = resolve_path_stack(ddc_code, ddc_tree)

            if path_stack:
                current_node = root
                for def_data in path_stack:
                    node_key = def_data.get('id', str(def_data['number']))

                    if node_key not in current_node.children:
                        f_name = get_folder_name(def_data)
                        full_path = os.path.join(current_node.full_path, f_name)
                        new_node = LibraryNode(f_name, full_path)
                        new_node.ddc_def = def_data
                        current_node.children[node_key] = new_node

                    current_node = current_node.children[node_key]

                current_node.add_file((src_path, filename))

    return root, map_updated


def balance_and_execute(node, threshold, dry_run, library_root, meta_map):
    """
    Revised to accept library_root for symlinking.
    """
    groups = defaultdict(list)
    groups[None].extend(node.files)

    for child_key, child_node in node.children.items():
        child_files = get_all_files_recursive(child_node)
        groups[child_key].extend(child_files)

    total_files = sum(len(f_list) for f_list in groups.values())
    sorted_keys = sorted([k for k in groups.keys() if k is not None],
                         key=lambda k: len(groups[k]), reverse=True)

    active_subfolders = set()
    current_load = total_files

    for key in sorted_keys:
        if current_load > threshold:
            active_subfolders.add(key)
            current_load -= len(groups[key])
        else:
            break

    has_content_here = (len(groups[None]) > 0) or (current_load > len(groups[None]))

    if has_content_here or active_subfolders:
        if not dry_run:
            os.makedirs(node.full_path, exist_ok=True)

    # Files destined for THIS level
    files_staying = groups[None][:]
    for key in groups:
        if key is not None and key not in active_subfolders:
            files_staying.extend(groups[key])

    for src, filename in files_staying:
        dst = os.path.join(node.full_path, filename)

        # 1. MOVE THE FILE
        if os.path.abspath(src) != os.path.abspath(dst):
            if dry_run:
                print(f"[MOVE] {filename} -> {node.folder_name}/")
            else:
                try:
                    shutil.move(src, dst)
                except shutil.Error as e:
                    print(f"Error moving {filename}: {e}")

        # 2. CREATE SYMLINK (Author Logic + Year Logic)
        if not dry_run:
            update_author_symlinks(dst, library_root)
            update_year_symlinks(dst, library_root, meta_map)

    # Recurse
    for key in active_subfolders:
        child_node = node.children[key]
        balance_and_execute(child_node, threshold, dry_run, library_root, meta_map)

def get_all_files_recursive(node):
    all_f = node.files[:]
    for child in node.children.values():
        all_f.extend(get_all_files_recursive(child))
    return all_f

def remove_empty_dirs(path, dry_run):
    if not os.path.isdir(path): return
    for root, dirs, files in os.walk(path, topdown=False):
        for name in dirs:
            # Don't delete our special Author directory!
            if name == BY_AUTHOR_DIR_NAME: continue
            if name == BY_YEAR_DIR_NAME: continue

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
            # Atomic reset: Rename to trash first, then create new, then delete trash.
            # This prevents race conditions or filesystem lag from leaving old folders.
            trash_name = f"{BY_AUTHOR_DIR_NAME}_trash_{int(time.time())}"
            trash_path = os.path.join(library_root, trash_name)

            try:
                os.rename(author_path, trash_path)
            except OSError as e:
                print(f"[WARN] Could not rename old author dir: {e}. Attempting direct delete.")
                shutil.rmtree(author_path, ignore_errors=True)
                trash_path = None # Moved to trash failed, so we don't try to delete trash

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

def main():
    parser = argparse.ArgumentParser(description="Reorganize Library (In-Place)")
    parser.add_argument("library_dir", help="Root directory of the library")
    parser.add_argument("--threshold", type=int, required=True, help="Max files per folder")
    parser.add_argument("--ddc-json", required=True, help="Path to ddc_map.json")
    parser.add_argument("--lt-json", required=True, help="Path to LibraryThing Export")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")

    args = parser.parse_args()
    root_dir = os.path.abspath(args.library_dir)

    if not os.path.exists(root_dir):
        print(f"Error: Directory '{root_dir}' does not exist.")
        return

    # 1. Load Data
    ddc_tree = load_ddc_index(args.ddc_json)
    meta_map = load_lt_metadata(args.lt_json)
    manual_map_path = os.path.join(root_dir, "manual_ddc_map.json")
    manual_map = load_json_map(manual_map_path)

    # 2. Reset Author Directory (Before scanning, to avoid scanning symlinks!)
    # We do this first so we don't accidentally index the symlinks as real files.
    reset_author_dir(root_dir, args.dry_run)
    reset_year_dir(root_dir, args.dry_run)

    # 3. Scan Files
    print(f"Scanning library: {root_dir}...")
    all_files = []
    for r, d, f in os.walk(root_dir):
        for file in f:
            # Skip hidden files, config files, and the Author dir itself (if it wasn't fully deleted)
            if BY_AUTHOR_DIR_NAME in r: continue
            if BY_YEAR_DIR_NAME in r: continue
            if file.startswith('.') or file in ["manual_ddc_map.json", "ddc_map.json", os.path.basename(__file__)]:
                continue

            # Avoid picking up symlinks if they exist elsewhere
            full_p = os.path.join(r, file)
            if not os.path.islink(full_p):
                all_files.append(full_p)

    # 4. Build Tree
    print("Analyzing structure...")
    virtual_root, map_updated = build_virtual_tree(all_files, meta_map, manual_map, ddc_tree, root_dir)

    # 5. Save Map
    if map_updated:
        if args.dry_run:
             print("[DRY RUN] manual_ddc_map.json would be updated.")
        else:
             print("Saving updated manual_ddc_map.json...")
             save_json_map(manual_map_path, manual_map)
    else:
        print("No new unknown files found. Map unchanged.")

    # 6. Execute Moves + Create Symlinks
    print(f"Reorganizing & Linking (Threshold: {args.threshold})...")
    for child_key, child_node in virtual_root.children.items():
        balance_and_execute(child_node, args.threshold, args.dry_run, root_dir, meta_map)

    # 7. Cleanup
    print("Cleaning up empty directories...")
    remove_empty_dirs(root_dir, args.dry_run)
    print("Done.")

if __name__ == "__main__":
    main()
