#!/bin/bash

# A simple script to stop an EC2 instance, change its type, and restart it.

INSTANCE_ID="$1"

NEW_INSTANCE_TYPE="${2:-t3a.nano}"

# Choice of "standard" or "unlimited".
CREDIT_MODE="${3:-standard}"

echo "Attempting to change instance type for $INSTANCE_ID to $NEW_INSTANCE_TYPE."

# Step 1: Stop the instance
echo "Stopping instance $INSTANCE_ID..."
aws ec2 stop-instances --instance-ids "$INSTANCE_ID"

# Use the 'wait' command to ensure the instance is fully stopped
echo "Waiting for instance $INSTANCE_ID to enter 'stopped' state..."
aws ec2 wait instance-stopped --instance-ids "$INSTANCE_ID"

echo "Instance $INSTANCE_ID has stopped."

# Step 2: Modify the instance type
echo "Modifying instance type to $NEW_INSTANCE_TYPE..."
aws ec2 modify-instance-attribute \
  --instance-id "$INSTANCE_ID" \
  --instance-type "{\"Value\": \"$NEW_INSTANCE_TYPE\"}"

echo "Instance type changed to $NEW_INSTANCE_TYPE."

# Step 3: Modify the credit specification to standard or unlimited
# This step is only relevant for burstable instance types (like T3).
echo "Setting credit specification to '$CREDIT_MODE'..."
aws ec2 modify-instance-credit-specification \
  --instance-credit-specification "InstanceId=$INSTANCE_ID,CpuCredits=$CREDIT_MODE"

echo "Instance type and credit specification have been updated."

# Step 4: Start the instance
echo "Starting instance $INSTANCE_ID..."
aws ec2 start-instances --instance-ids "$INSTANCE_ID"

# Optional: Wait for the instance to be running again
echo "Waiting for instance $INSTANCE_ID to enter 'running' state..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

echo "Instance $INSTANCE_ID is now running with the new type: $NEW_INSTANCE_TYPE."
