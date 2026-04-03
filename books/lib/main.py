import argparse
import os

from .cleanup import remove_empty_dirs, reset_author_dir, reset_year_dir, reset_collections_dir
from .config import BY_AUTHOR_DIR_NAME, BY_YEAR_DIR_NAME, COLLECTIONS_DIR_NAME
from .maps import load_ddc_index, load_lt_metadata, load_json_map, save_json_map, build_collection_index
from .tree import build_virtual_tree, balance_and_execute


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

    ddc_tree = load_ddc_index(args.ddc_json)
    meta_map = load_lt_metadata(args.lt_json)
    manual_map_path = os.path.join(root_dir, "manual_ddc_map.json")
    manual_map = load_json_map(manual_map_path)
    collections_map_path = os.path.join(root_dir, "collections.json")
    collections_map = load_json_map(collections_map_path)
    collection_index = build_collection_index(collections_map)

    reset_author_dir(root_dir, args.dry_run)
    reset_year_dir(root_dir, args.dry_run)
    reset_collections_dir(root_dir, args.dry_run)

    print(f"Scanning library: {root_dir}...")
    all_files = []
    for r, d, f in os.walk(root_dir):
        for file in f:
            if BY_AUTHOR_DIR_NAME in r:
                continue
            if BY_YEAR_DIR_NAME in r:
                continue
            if COLLECTIONS_DIR_NAME in r:
                continue
            if file.startswith('.') or file in ["manual_ddc_map.json", "ddc_map.json", os.path.basename(__file__)]:
                continue
            if file == "collections.json":
                continue

            full_p = os.path.join(r, file)
            if not os.path.islink(full_p):
                all_files.append(full_p)

    print("Analyzing structure...")
    virtual_root, map_updated = build_virtual_tree(all_files, meta_map, manual_map, ddc_tree, root_dir)

    if map_updated:
        if args.dry_run:
            print("[DRY RUN] manual_ddc_map.json would be updated.")
        else:
            print("Saving updated manual_ddc_map.json...")
            save_json_map(manual_map_path, manual_map)
    else:
        print("No new unknown files found. Map unchanged.")

    print(f"Reorganizing & Linking (Threshold: {args.threshold})...")
    for child_key, child_node in virtual_root.children.items():
        balance_and_execute(child_node, args.threshold, args.dry_run, root_dir, meta_map, collection_index)

    print("Cleaning up empty directories...")
    remove_empty_dirs(root_dir, args.dry_run)
    print("Done.")


if __name__ == "__main__":
    main()
