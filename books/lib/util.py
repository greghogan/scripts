import re


def clean_asin(ident):
    if not ident:
        return ""
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
    match = re.search(r'.* by (.+?) \[', filename)
    if not match:
        return []

    raw_author_str = match.group(1)

    clean_str = raw_author_str.replace(", and ", ",").replace(" and ", ",")

    authors = []
    for a in clean_str.split(','):
        a_clean = re.sub(r'\(.*?\)', '', a).strip()
        if a_clean:
            authors.append(a_clean)
    return authors


def parse_ddc_num(num_str):
    try:
        return float(str(num_str).strip())
    except ValueError:
        return 0.0


def resolve_path_stack(ddc_code, ddc_tree):
    if not ddc_code:
        return []

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
                    next_val = parse_ddc_num(valid_nodes[i + 1]['number'])
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


def get_all_files_recursive(node):
    all_f = node.files[:]
    for child in node.children.values():
        all_f.extend(get_all_files_recursive(child))
    return all_f
