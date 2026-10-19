import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from resolver import resolve_link

app = FastAPI(
    title="Link Resolver API",
    version="1.0.0",
)


class ResolveRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


@app.get("/")
async def home():
    return {
        "name": "Link Resolver API",
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/api/resolve")
async def resolve(request: ResolveRequest):
    try:
        result = await asyncio.wait_for(
            resolve_link(request.url),
            timeout=20,
        )
        return result
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Resolution timed out.",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )
