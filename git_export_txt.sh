#!/bin/bash

# To remove the ".txt" extensions
find . -type f -name "*.txt" -exec sh -c 'mv "$1" "${1%.txt}"' _ {} \;


# 1. Determine the Commit Hash
if [ -n "$1" ]; then
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

# 3. Export the commit snapshot to the temp directory
# We pipe git archive to tar to extract files without creating an intermediate archive
if ! git archive "$COMMIT" --format=tar 2>/dev/null | tar -x -C "$TEMP_DIR"; then
    echo "Error: Commit '$COMMIT' not found."
    rm -rf "$TEMP_DIR"
    exit 1
fi

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
cd - > /dev/null
rm -rf "$TEMP_DIR"

echo "Success! Created ${COMMIT}.zip"
