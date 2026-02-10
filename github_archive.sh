#!/bin/bash

# --- 1. CONFIGURATION ---

CONFIRM_MODE=false
SINCE_DATE=""

usage() {
    echo "Usage: $0 [-c] <date>"
    echo "  -c, --confirm   Interactive mode: Show dates and ask before checking."
    echo "  <date>          Date to check for updates (e.g., '2024-01-01')"
    exit 1
}

# Parse Arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -c|--confirm) CONFIRM_MODE=true ;;
        -h|--help) usage ;;
        -*) echo "Unknown option: $1"; usage ;;
        *) 
            if [ -z "$SINCE_DATE" ]; then
                SINCE_DATE="$1"
            else
                echo "Error: Multiple dates specified."
                usage
            fi
            ;;
    esac
    shift
done

# Validate Input
if [ -z "$SINCE_DATE" ]; then
    echo "Error: Date argument is missing."
    usage
fi

# Check Tools
if ! command -v gh &> /dev/null; then echo "Error: 'gh' not installed."; exit 1; fi
if ! command -v zstd &> /dev/null; then echo "Error: 'zstd' not installed."; exit 1; fi

# Check Auth
echo "Verifying GitHub authentication..."
if ! gh auth status &> /dev/null; then
    echo "Error: Not logged in. Run 'gh auth login'."
    exit 1
fi

# --- 2. FETCH REPO LIST (WITH DATES) ---

echo "Fetching repository list and dates..."

# Template for consistent output: "sshUrl|pushedAt"
TEMPLATE_OWNED='{{range .}}{{printf "%s|%s\n" .sshUrl .pushedAt}}{{end}}'
TEMPLATE_STARRED='{{range .}}{{printf "%s|%s\n" .ssh_url .pushed_at}}{{end}}'

# Get Owned Repos
OWNED=$(gh repo list --limit 5000 --json sshUrl,pushedAt --template "$TEMPLATE_OWNED")

# Get Starred Repos
STARRED=$(gh api user/starred --paginate --template "$TEMPLATE_STARRED")

# Combine, Sort, Unique, and Remove Empty Lines
ALL_DATA=$(echo -e "$OWNED\n$STARRED" | sort -u | grep -v "^|")
REPO_COUNT=$(echo "$ALL_DATA" | wc -l | xargs)

if [ "$REPO_COUNT" -eq 0 ]; then
    echo "No repositories found."
    exit 0
fi

echo "Found $REPO_COUNT repositories."
echo "Checking for updates since: $SINCE_DATE"
echo "------------------------------------------------"

# --- 3. MAIN LOOP ---

# We read from File Descriptor 3 (<<< "$ALL_DATA") to free up stdin for user prompts
while read -r line <&3; do
    
    # Split line into URL and DATE
    repo_url="${line%|*}"
    push_date="${line#*|}"
    
    # Simplify Date (2024-02-09T10:00:00Z -> 2024-02-09)
    simple_date=$(echo "$push_date" | cut -d'T' -f1)

    # Naming Logic
    clean_url="${repo_url%.git}"
    repo_name=$(basename "$clean_url")
    user_name=$(basename $(dirname "$clean_url") | cut -d':' -f2)
    folder_name="${user_name}_${repo_name}.git"
    archive_name="${folder_name%.git}.tar.zst"

    # --- INTERACTIVE PROMPT ---
    should_process=true
    
    if [ "$CONFIRM_MODE" = true ]; then
        echo -n "Repo: $user_name/$repo_name (Last Push: $simple_date) [y/n/q]: "
        read -n 1 -r reply < /dev/tty
        echo "" # Newline

        case "$reply" in
            y|Y) 
                should_process=true 
                ;;
            q|Q) 
                echo "Quitting..."
                exit 0 
                ;;
            *) 
                should_process=false 
                ;;
        esac
    fi

    if [ "$should_process" = true ]; then
        echo "Processing $user_name/$repo_name..."

        # 1. Setup Bare Repo
        mkdir -p "$folder_name"
        git --git-dir="$folder_name" init --bare --quiet
        
        # 2. Configure Remote
        if git --git-dir="$folder_name" remote | grep -q origin; then
            git --git-dir="$folder_name" remote set-url origin "$repo_url"
        else
            git --git-dir="$folder_name" remote add origin "$repo_url"
        fi
        git --git-dir="$folder_name" config remote.origin.fetch "+refs/heads/*:refs/heads/*"

        # 3. SHALLOW PEEK
        if git --git-dir="$folder_name" fetch origin --depth=1 --quiet; then
            
            # Check for changes since DATE
            change_count=$(git --git-dir="$folder_name" rev-list --all --since="$SINCE_DATE" --count)

            if [ "$change_count" -gt 0 ]; then
                echo "   [UPDATED] Downloading full history..."
                git --git-dir="$folder_name" fetch --unshallow --quiet
                
                echo "   - Optimizing database..."
                git --git-dir="$folder_name" gc --aggressive --prune=now --quiet
                
                echo "   - Compressing..."
                # Added --quiet to suppress zstd summary output
                tar -c -f - "$folder_name" | zstd -19 -T0 --quiet -o "$archive_name"
                echo "   - Done."
            else
                echo "   [NO CHANGE] Skipped."
            fi
        else
            echo "   [ERROR] Repo not found or access denied."
        fi

        # 4. CLEANUP
        rm -rf "$folder_name"
    fi

done 3<<< "$ALL_DATA"
