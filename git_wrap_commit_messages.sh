#!/bin/bash

set -euo pipefail

WIDTH=72
YES=false
DRY_RUN=false
REV_ARGS=()

usage() {
    echo "Usage: $0 [-n|--dry-run] [-y|--yes] [-w|--width N] [N] [<rev-list options>...]"
    echo ""
    echo "Word wrap commit message bodies over N characters, preserving subjects."
    echo "By default, N is 72 and the current branch history is rewritten."
    echo ""
    echo "Options:"
    echo "  -w, --width N   Body wrap width. Default: 72."
    echo "  -n, --dry-run   Print proposed changes without rewriting history."
    echo "  -y, --yes       Accept all proposed message changes without prompting."
    echo "  -h, --help      Show this help."
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  $0 80"
    echo "  $0 --dry-run --width 72 -- HEAD~10..HEAD"
    echo "  $0 --width 72 -- HEAD~10..HEAD"
    echo "  $0 -y -- --all"
}

is_positive_integer() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -y|--yes)
            YES=true
            ;;
        -n|--dry-run)
            DRY_RUN=true
            ;;
        -w|--width)
            shift
            if [[ "$#" -eq 0 ]] || ! is_positive_integer "$1"; then
                echo "Error: --width requires a positive integer." >&2
                usage
                exit 1
            fi
            WIDTH="$1"
            ;;
        --width=*)
            WIDTH="${1#*=}"
            if ! is_positive_integer "$WIDTH"; then
                echo "Error: --width requires a positive integer." >&2
                usage
                exit 1
            fi
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            REV_ARGS+=("$@")
            break
            ;;
        -*)
            REV_ARGS+=("$1")
            ;;
        *)
            if [[ ${#REV_ARGS[@]} -eq 0 ]] && [[ "$WIDTH" == "72" ]] && is_positive_integer "$1"; then
                WIDTH="$1"
            else
                REV_ARGS+=("$1")
            fi
            ;;
    esac
    shift
done

if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "Error: Current directory is not a git repository." >&2
    exit 1
fi

if [[ "$DRY_RUN" != "true" ]] && { ! git diff --quiet || ! git diff --cached --quiet; }; then
    echo "Error: Working tree has uncommitted changes. Commit or stash them first." >&2
    exit 1
fi

if [[ "$DRY_RUN" != "true" ]] && [[ -d "$(git rev-parse --git-path refs/original)" ]]; then
    echo "Error: refs/original already exists from a previous filter-branch run." >&2
    echo "Review and remove it before rewriting history again." >&2
    exit 1
fi

if [[ ${#REV_ARGS[@]} -eq 0 ]]; then
    REV_ARGS=(HEAD)
fi

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

FILTER="$TMP_DIR/msg-filter.sh"

cat > "$FILTER" <<'FILTER_SCRIPT'
#!/bin/bash

set -euo pipefail

WIDTH=${WRAP_COMMIT_MSG_WIDTH:?}
YES=${WRAP_COMMIT_MSG_YES:?}
DRY_RUN=${WRAP_COMMIT_MSG_DRY_RUN:-false}
COMMIT=${GIT_COMMIT:-unknown}
ORIGINAL_FILE=$(mktemp)
NEW_FILE=$(mktemp)
BODY_FILE=$(mktemp)
trap 'rm -f "$ORIGINAL_FILE" "$NEW_FILE" "$BODY_FILE"' EXIT

cat > "$ORIGINAL_FILE"

wrap_body() {
    awk -v width="$WIDTH" '
        function flush(    i, cmd) {
            if (count == 0) {
                return
            }

            if (!too_long) {
                for (i = 1; i <= count; i++) {
                    print lines[i]
                }
                count = 0
                return
            }

            cmd = "fmt -w " width
            for (i = 1; i <= count; i++) {
                print lines[i] | cmd
            }
            close(cmd)
            count = 0
            too_long = 0
        }

        function literal_line(line) {
            return line ~ /^([[:space:]]|[-*+] |[0-9][.)] |>|[A-Za-z0-9-]+:[[:space:]]|Signed-off-by:|Co-authored-by:)/
        }

        /^$/ {
            flush()
            print
            next
        }

        literal_line($0) {
            flush()
            print
            next
        }

        {
            lines[++count] = $0
            if (length($0) > width) {
                too_long = 1
            }
        }

        END {
            flush()
        }
    '
}

SUBJECT=$(sed -n '1p' "$ORIGINAL_FILE")
SECOND_LINE=$(sed -n '2p' "$ORIGINAL_FILE")
LINE_COUNT=$(wc -l < "$ORIGINAL_FILE")

if [[ "$LINE_COUNT" -ge 2 ]] && [[ -z "$SECOND_LINE" ]]; then
    tail -n +3 "$ORIGINAL_FILE" | wrap_body > "$BODY_FILE"
    {
        printf '%s\n\n' "$SUBJECT"
        cat "$BODY_FILE"
    } > "$NEW_FILE"
else
    cat "$ORIGINAL_FILE" > "$NEW_FILE"
fi

if cmp -s "$NEW_FILE" "$ORIGINAL_FILE"; then
    if [[ "$DRY_RUN" == "true" ]]; then
        exit 0
    fi
    cat "$ORIGINAL_FILE"
    exit 0
fi

if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "Commit: $COMMIT"
    echo "----- OLD MESSAGE -----"
    cat "$ORIGINAL_FILE"
    echo "----- NEW MESSAGE -----"
    cat "$NEW_FILE"
    echo "-----------------------"
    exit 0
fi

if [[ "$YES" == "true" ]]; then
    cat "$NEW_FILE"
    exit 0
fi

{
    echo ""
    echo "Commit: $COMMIT"
    echo "----- OLD MESSAGE -----"
    cat "$ORIGINAL_FILE"
    echo "----- NEW MESSAGE -----"
    cat "$NEW_FILE"
    echo "-----------------------"
    printf "Rewrite this commit message? [y/N/q] "
} > /dev/tty

read -r reply < /dev/tty
case "$reply" in
    y|Y|yes|YES)
        cat "$NEW_FILE"
        ;;
    q|Q|quit|QUIT)
        echo "Aborted by user." > /dev/tty
        exit 130
        ;;
    *)
        cat "$ORIGINAL_FILE"
        ;;
esac
FILTER_SCRIPT

chmod +x "$FILTER"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "Checking commit message bodies at width $WIDTH."
else
    echo "Rewriting commit message bodies at width $WIDTH."
fi
echo "Revision arguments: ${REV_ARGS[*]}"

if [[ "$DRY_RUN" == "true" ]]; then
    echo "Dry run only. No refs will be changed."

    changed=0
    while IFS= read -r commit; do
        output=$(
            GIT_COMMIT="$commit" \
            WRAP_COMMIT_MSG_WIDTH="$WIDTH" \
            WRAP_COMMIT_MSG_YES="$YES" \
            WRAP_COMMIT_MSG_DRY_RUN=true \
            "$FILTER" < <(git log -1 --format=%B "$commit")
        )

        if [[ -n "$output" ]]; then
            printf '%s\n' "$output"
            changed=$((changed + 1))
        fi
    done < <(git rev-list --reverse "${REV_ARGS[@]}")

    if [[ "$changed" -eq 0 ]]; then
        echo "No commit message bodies would change."
    fi

    exit 0
fi

echo "This rewrites Git history. Existing refs will need to be force-pushed if shared."

if [[ "$YES" != "true" ]]; then
    echo "You will be prompted for each commit whose body would change."
fi

WRAP_COMMIT_MSG_WIDTH="$WIDTH" \
WRAP_COMMIT_MSG_YES="$YES" \
WRAP_COMMIT_MSG_DRY_RUN=false \
FILTER_BRANCH_SQUELCH_WARNING=1 \
git filter-branch --msg-filter "$FILTER" -- "${REV_ARGS[@]}"
