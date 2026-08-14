#!/bin/bash

# ==========================================
# CONFIGURATION
# ==========================================
# Command to execute when the first session starts working (0 -> 1)
SESSION_START_CMD="true"

# Command to execute when the last session finishes working (1 -> 0)
SESSION_STOP_CMD="true"
# ==========================================

# echo <<EOF > .codex/hooks.json 
# {
#   "hooks": {
#     "UserPromptSubmit": [
#       {
#         "hooks": [
#           {
#             "type": "command",
#             "command": "/path/to/codex-session-manager.sh",
#             "timeout": 15
#           }
#         ]
#       }
#     ],
#     "Stop": [
#       {
#         "hooks": [
#           {
#             "type": "command",
#             "command": "/path/to/codex-session-manager.sh",
#             "timeout": 15
#           }
#         ]
#       }
#     ],
#     "SessionEnd": [
#       {
#         "hooks": [
#           {
#             "type": "command",
#             "command": "/path/to/codex-session-manager.sh",
#             "timeout": 3
#           }
#         ]
#       }
#     ]
#   }
# }
# EOF


# Read the payload from stdin
PAYLOAD=$(cat -)

EVENT=$(echo "$PAYLOAD" | jq -r '.hook_event_name')
SESSION_ID=$(echo "$PAYLOAD" | jq -r '.session_id')

# Define tracking paths (Renamed to reflect "working" state rather than just active)
WORKING_DIR="/tmp/codex-session-manager"
LOCK_FILE="/tmp/codex-session-manager.lock"

# Ensure the tracking directory exists
mkdir -p "$WORKING_DIR"

# Use flock to ensure atomic, concurrency-safe tracking
(
    # Acquire an exclusive lock on file descriptor 9
    flock -x 9
    
    if [[ "$EVENT" == "UserPromptSubmit" ]]; then
        # Count active workers BEFORE we register this one
        ACTIVE_COUNT_BEFORE=$(ls -1q "$WORKING_DIR" | wc -l)
        
        # Register this session as actively working
        touch "$WORKING_DIR/$SESSION_ID"
        
        # If the count was 0, this is the very first agent to start working
        if [[ "$ACTIVE_COUNT_BEFORE" -eq 0 ]]; then
            eval "$SESSION_START_CMD" >/dev/null
        fi
        
    elif [[ "$EVENT" == "Stop" || "$EVENT" == "SessionEnd" ]]; then
        # Only proceed if this session is currently marked as working
        if [[ -f "$WORKING_DIR/$SESSION_ID" ]]; then
            
            # Unregister this session
            rm -f "$WORKING_DIR/$SESSION_ID"
            
            # Count remaining active workers AFTER removing this one
            ACTIVE_COUNT_AFTER=$(ls -1q "$WORKING_DIR" | wc -l)
            
            # If the count is now 0, the last agent just finished
            if [[ "$ACTIVE_COUNT_AFTER" -eq 0 ]]; then
                eval "$SESSION_STOP_CMD" >/dev/null
            fi
        fi
    fi

) 9> "$LOCK_FILE"

# Stop hook stdout is a JSON protocol channel. An empty object accepts the stop.
if [[ "$EVENT" == "Stop" ]]; then
    printf '{}\n'
fi

exit 0
