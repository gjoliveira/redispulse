
import os
import redis
from fastapi import FastAPI, HTTPException

app = FastAPI(title="RedisPulse")

redis_client = redis.Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379"),
    decode_responses=True,
)


@app.get("/")
def home():
    return {"message": "RedisPulse API is running"}


@app.get("/health")
def health():
    try:
        redis_client.ping()
        return {"api": "ok", "redis": "connected"}
    except redis.RedisError:
        raise HTTPException(
            status_code=503,
            detail="Redis is unavailable",
        )
