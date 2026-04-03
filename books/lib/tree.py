import os
import re
import shutil
from collections import defaultdict

from .models import LibraryNode
from .util import get_folder_name, resolve_path_stack, get_all_files_recursive, clean_asin
from .symlinks import update_author_symlinks, update_year_symlinks, update_collection_symlinks


def build_virtual_tree(files, meta_map, manual_map, ddc_tree, library_root):
    root = LibraryNode("ROOT", library_root)
    regex_asin = re.compile(r'\[([A-Z0-9]+)\]')
    map_updated = False

    print(f"Processing {len(files)} files...")

    for src_path in files:
        filename = os.path.basename(src_path)

        match = regex_asin.search(filename)
        ddc_code = None

        if match:
            asin = clean_asin(match.group(1))
            if asin in meta_map:
                ddc_code = meta_map[asin].get('ddc')

        if not ddc_code:
            if filename in manual_map:
                ddc_code = manual_map[filename]
            else:
                print(f"[NEW] Tracking unknown file: {filename}")
                manual_map[filename] = None
                map_updated = True

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


def balance_and_execute(node, threshold, dry_run, library_root, meta_map, collection_index):
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

    files_staying = groups[None][:]
    for key in groups:
        if key is not None and key not in active_subfolders:
            files_staying.extend(groups[key])

    for src, filename in files_staying:
        dst = os.path.join(node.full_path, filename)

        if os.path.abspath(src) != os.path.abspath(dst):
            if dry_run:
                print(f"[MOVE] {filename} -> {node.folder_name}/")
            else:
                try:
                    shutil.move(src, dst)
                except shutil.Error as e:
                    print(f"Error moving {filename}: {e}")

        if not dry_run:
            update_author_symlinks(dst, library_root)
            update_year_symlinks(dst, library_root, meta_map)
            update_collection_symlinks(dst, library_root, collection_index)

    for key in active_subfolders:
        child_node = node.children[key]
        balance_and_execute(child_node, threshold, dry_run, library_root, meta_map, collection_index)
