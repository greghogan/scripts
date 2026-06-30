#!/bin/bash

# To remove the ".txt" extensions:
# find . -type f -name "*.txt" -exec sh -c 'mv "$1" "${1%.txt}"' _ {} \;

set -euo pipefail

ORIGINAL_PWD=$PWD
TEMP_DIR=""

cleanup() {
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}

resolve_submodule_git_dir() {
    local parent_repo_ref=$1
    local submodule_path=$2
    local parent_worktree
    local worktree_repo
    local modules_repo

    parent_worktree=$(git -C "$parent_repo_ref" rev-parse --show-toplevel 2>/dev/null || true)
    if [ -n "$parent_worktree" ]; then
        worktree_repo="${parent_worktree}/${submodule_path}"
        if [ -d "$worktree_repo" ] && git -C "$worktree_repo" rev-parse --git-dir > /dev/null 2>&1; then
            printf '%s\n' "$worktree_repo"
            return 0
        fi
    fi

    modules_repo=$(git -C "$parent_repo_ref" rev-parse --path-format=absolute --git-path "modules/$submodule_path" 2>/dev/null || true)
    if [ -n "$modules_repo" ] && [ -d "$modules_repo" ]; then
        printf '%s\n' "$modules_repo"
        return 0
    fi

    return 1
}

export_submodules() {
    local repo_ref=$1
    local treeish=$2
    local destination=$3
    local git_cmd=(git -C "$repo_ref")
    local gitmodules_path="${destination}/.gitmodules"
    local path_line
    local config_key
    local submodule_path
    local submodule_commit
    local submodule_repo

    if [ ! -f "$gitmodules_path" ]; then
        return 0
    fi

    while IFS= read -r path_line; do
        config_key=${path_line%% *}
        submodule_path=${path_line#* }
        submodule_commit=$("${git_cmd[@]}" ls-tree "$treeish" -- "$submodule_path" | awk '$1 == "160000" { print $3 }')

        if [ -z "$submodule_commit" ]; then
            echo "Warning: Could not resolve submodule commit for '$submodule_path' in '$treeish'." >&2
            continue
        fi

        if ! submodule_repo=$(resolve_submodule_git_dir "$repo_ref" "$submodule_path"); then
            echo "Warning: Submodule repository for '$submodule_path' is not available locally; skipping its contents." >&2
            continue
        fi

        mkdir -p "${destination}/${submodule_path}"
        if ! git -C "$submodule_repo" archive "$submodule_commit" --format=tar 2>/dev/null | tar -x -C "${destination}/${submodule_path}"; then
            echo "Warning: Failed to export submodule '$submodule_path' at commit '$submodule_commit'; skipping." >&2
            rm -rf "${destination:?}/${submodule_path}"
            continue
        fi

        find "${destination}/${submodule_path}" ! -type f ! -type d -delete
        export_submodules "$submodule_repo" "$submodule_commit" "${destination}/${submodule_path}"
    done < <(git config -f "$gitmodules_path" --get-regexp '^submodule\..*\.path$' 2>/dev/null || true)
}


# 1. Determine the Commit Hash
if [ -n "${1-}" ]; then
    COMMIT=$1
else
    # Check if we are actually in a git repo
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        echo "Error: Current directory is not a git repository."
        exit 1
    fi
    # Get the short hash of the current HEAD
    COMMIT=$(git rev-parse --short HEAD)
    echo "No commit specified. Using latest commit: $COMMIT"
fi

# 2. Create a safe temporary directory
TEMP_DIR=$(mktemp -d)
trap cleanup EXIT

# 3. Export the commit snapshot to the temp directory
# We pipe git archive to tar to extract files without creating an intermediate archive
if ! git archive "$COMMIT" --format=tar 2>/dev/null | tar -x -C "$TEMP_DIR"; then
    echo "Error: Commit '$COMMIT' not found."
    exit 1
fi

# 3b. Export submodule snapshots recorded by the commit.
export_submodules "." "$COMMIT" "$TEMP_DIR"

# 4. Remove non-regular files (symlinks, etc.)
find "$TEMP_DIR" ! -type f ! -type d -delete

# 5. Append .txt to all regular files
# We use 'find' to handle subdirectories recursively
find "$TEMP_DIR" -type f -exec mv "{}" "{}.txt" \;

# 6. Zip the contents
# We save the current path so we can write the zip file back here
OUTPUT_PATH="${PWD}/${COMMIT}.zip"

# cd into TEMP_DIR so the zip doesn't include the full /tmp/ path structure
cd "$TEMP_DIR" && zip --recurse-paths --quiet "$OUTPUT_PATH" .

# 7. Cleanup
cd "$ORIGINAL_PWD"

echo "Success! Created ${COMMIT}.zip"
