# redis_client.py
import os, redis

REDIS_URL = "redis://localhost:6379"

# Redis connection
r = redis.Redis(host='localhost', port=6379, decode_responses=True)
# r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
print(f"Connecting to Redis at {r}")

