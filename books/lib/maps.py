import json
import os
from collections import defaultdict

from .util import clean_asin


def load_json_map(path):
    if path and os.path.exists(path):
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

        if 'ddc' in book and 'code' in book['ddc']:
            raw = book['ddc']['code']
            ddc_code = raw[0] if isinstance(raw, list) else raw
            val_map['ddc'] = str(ddc_code).strip()

        if 'date' in book:
            val_map['year'] = str(book['date']).strip()

        if not val_map:
            continue

        ids = set()
        if 'asin' in book:
            ids.add(clean_asin(book['asin']))
        if 'isbn' in book and isinstance(book['isbn'], dict):
            for v in book['isbn'].values():
                ids.add(clean_asin(v))

        for i in ids:
            if i:
                meta_map[i] = val_map

    return meta_map


def load_ddc_index(index_path):
    print(f"Loading DDC Map: {index_path}...")
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return [data]
            return data
    except FileNotFoundError:
        print(f"Error: DDC Map file {index_path} not found.")
        return []


def normalize_collection_name(name):
    return str(name).replace('/', '-').strip()


def build_collection_index(collections_map):
    index = defaultdict(set)
    if not isinstance(collections_map, dict):
        return index

    for collection_name, asins in collections_map.items():
        if not isinstance(asins, list):
            continue
        safe_name = normalize_collection_name(collection_name)
        if not safe_name:
            continue
        for asin in asins:
            clean = clean_asin(asin)
            if clean:
                index[clean].add(safe_name)
    return index
