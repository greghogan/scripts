#!/bin/bash

# A script to find EC2 instances by name, and if their type differs from the
# target type, stop them, change the type, and restart them.

# --- Script Setup ---
# Exit immediately if a command exits with a non-zero status.
set -e
# Treat unset variables as an error.
set -u
# Ensures that a pipeline command returns a non-zero status if any command in the pipeline fails.
set -o pipefail

# The string to search for in the 'Name' tag of the instances.
# Wildcards are not needed here; the script adds them.
INSTANCE_NAME_FILTER="$1"

NEW_INSTANCE_TYPE="${2:-t3a.nano}"
# Default to 'standard' if the second argument is not provided.
CREDIT_MODE="${3:-standard}"

echo "--- Script Starting ---"
echo "Target Instance Type: $NEW_INSTANCE_TYPE"
echo "Target Credit Mode:   $CREDIT_MODE"
echo "Instance Name Filter: '*${INSTANCE_NAME_FILTER}*'"
echo "-----------------------"
echo ""

# --- Main Logic ---

# Step 1: Fetch all instances matching the name filter that are running or stopped.
# The 'query' fetches the Instance ID, its current Type, and the value of its 'Name' tag.
# The 'output' is formatted as plain text, which is easy to parse in a shell loop.
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=*${INSTANCE_NAME_FILTER}*" "Name=instance-state-name,Values=running,stopped" \
  --query "Reservations[].Instances[].[InstanceId, InstanceType, Tags[?Key=='Name'].Value | [0]]" \
  --output text | while read -r INSTANCE_ID CURRENT_TYPE INSTANCE_NAME; do

  echo "Processing Instance: $INSTANCE_ID ($INSTANCE_NAME)"
  echo "  -> Current Type: $CURRENT_TYPE"

  # Step 2: Check if the instance type needs to be changed.
  if [ "$CURRENT_TYPE" == "$NEW_INSTANCE_TYPE" ]; then
    echo "  -> SKIPPING: Instance is already the target type ($NEW_INSTANCE_TYPE)."
    echo "------------------------------------------------------------"
    continue # Move to the next instance in the loop
  fi

  echo "  -> ACTION: Type change required ($CURRENT_TYPE -> $NEW_INSTANCE_TYPE)."

  # --- Begin Stop/Modify/Start Cycle ---

  # Step 3: Stop the instance if it's running.
  # First, check if it's actually running before trying to stop it.
  INSTANCE_STATE=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --query "Reservations[].Instances[].State.Name" --output text)
  if [ "$INSTANCE_STATE" == "running" ]; then
      echo "  Stopping instance..."
      aws ec2 stop-instances --instance-ids "$INSTANCE_ID" > /dev/null
      aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"
      echo "  Instance is stopped."
  else
      echo "  Instance is already stopped."
  fi

  # Step 4: Modify the instance type.
  echo "  Modifying instance type to $NEW_INSTANCE_TYPE..."
  aws ec2 modify-instance-attribute \
    --instance-id "$INSTANCE_ID" \
    --instance-type "{\"Value\": \"$NEW_INSTANCE_TYPE\"}"

  # Step 5: Modify the credit specification.
  # This is only relevant for burstable instance types (like T-family).
  echo "  Setting credit specification to '$CREDIT_MODE'..."
  aws ec2 modify-instance-credit-specification \
    --instance-credit-specification "InstanceId=$INSTANCE_ID,CpuCredits=$CREDIT_MODE"

  echo "  Instance attributes have been updated."

  # Step 6: Start the instance.
  echo "  Starting instance..."
  aws ec2 start-instances --instance-ids "$INSTANCE_ID" > /dev/null

  # Optional: Wait for the instance to be running again.
  echo "  Waiting for instance to enter 'running' state..."
  aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

  echo "  SUCCESS: Instance $INSTANCE_ID is now running as $NEW_INSTANCE_TYPE."
  echo "------------------------------------------------------------"

done

echo ""
echo "--- Script Finished ---"
