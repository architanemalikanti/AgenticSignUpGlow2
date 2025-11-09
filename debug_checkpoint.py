#!/usr/bin/env python3
"""
Debug script to inspect the structure of SQLite checkpoints.
"""
import sqlite3
import msgpack
import pickle
import json
from pathlib import Path
from pprint import pprint

# Session ID from the recent test
session_id = "76d894a4-f9fd-48ea-9a97-ed36d69ca576"

# Get path to conversations.db
db_path = str(Path(__file__).parent / "conversations.db")

# Connect to SQLite and get the latest checkpoint
sqlite_conn = sqlite3.connect(db_path)
cursor = sqlite_conn.cursor()

# Get the most recent checkpoint
cursor.execute("""
    SELECT checkpoint, metadata, checkpoint_id
    FROM checkpoints
    WHERE thread_id = ?
    ORDER BY checkpoint_id DESC
    LIMIT 1
""", (session_id,))

row = cursor.fetchone()
if not row:
    print(f"❌ No checkpoint found for session {session_id}")
    sqlite_conn.close()
    exit(1)

checkpoint_blob, metadata_blob, checkpoint_id = row
print(f"✅ Found checkpoint {checkpoint_id} for session {session_id}")

# Try to decode with msgpack first
try:
    checkpoint_data = msgpack.unpackb(checkpoint_blob, raw=False)
    print("\n✅ Decoded with msgpack")
except Exception as e1:
    try:
        checkpoint_data = pickle.loads(checkpoint_blob)
        print("\n✅ Decoded with pickle")
    except Exception as e2:
        print(f"\n❌ Failed to decode: msgpack={e1}, pickle={e2}")
        sqlite_conn.close()
        exit(1)

# Print the top-level structure
print("\n" + "="*80)
print("CHECKPOINT TOP-LEVEL KEYS:")
print("="*80)
if isinstance(checkpoint_data, dict):
    for key in checkpoint_data.keys():
        print(f"  - {key}: {type(checkpoint_data[key])}")
else:
    print(f"Checkpoint is not a dict, it's a {type(checkpoint_data)}")

# Print channel_values if it exists
print("\n" + "="*80)
print("CHANNEL_VALUES:")
print("="*80)
if isinstance(checkpoint_data, dict):
    channel_values = checkpoint_data.get('channel_values', {})
    if channel_values:
        print(f"Type: {type(channel_values)}")
        if isinstance(channel_values, dict):
            for key in channel_values.keys():
                value = channel_values[key]
                print(f"\n  Key: {key}")
                print(f"  Type: {type(value)}")
                if isinstance(value, list):
                    print(f"  Length: {len(value)}")
                    if len(value) > 0:
                        print(f"  First item type: {type(value[0])}")
                        print(f"  First item: {value[0]}")
    else:
        print("No channel_values found")
else:
    print("checkpoint_data is not a dict")

# Look for messages specifically
print("\n" + "="*80)
print("SEARCHING FOR MESSAGES:")
print("="*80)

def search_for_messages(obj, path="root"):
    """Recursively search for message-like structures"""
    if isinstance(obj, dict):
        # Check if this dict looks like a message
        if 'content' in obj or 'type' in obj or 'role' in obj:
            print(f"\n📧 Found message-like object at {path}:")
            pprint(obj, depth=2)

        # Check for 'messages' key
        if 'messages' in obj:
            print(f"\n📨 Found 'messages' key at {path}:")
            messages = obj['messages']
            print(f"  Type: {type(messages)}")
            if isinstance(messages, list):
                print(f"  Length: {len(messages)}")
                if len(messages) > 0:
                    print(f"  First message:")
                    pprint(messages[0], depth=3)

        # Recurse into dict values
        for key, value in obj.items():
            if key not in ['checkpoint', 'metadata']:  # Skip these to avoid noise
                search_for_messages(value, f"{path}.{key}")

    elif isinstance(obj, list):
        for i, item in enumerate(obj[:3]):  # Only check first 3 items to avoid spam
            search_for_messages(item, f"{path}[{i}]")

search_for_messages(checkpoint_data)

# Print full checkpoint structure (limited depth)
print("\n" + "="*80)
print("FULL CHECKPOINT STRUCTURE (limited depth):")
print("="*80)
pprint(checkpoint_data, depth=3)

sqlite_conn.close()
print("\n✅ Debug complete")
