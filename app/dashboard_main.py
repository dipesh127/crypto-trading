from __future__ import annotations
import asyncio
import asyncpg
import uvicorn
from app.config import get_settings
from app.dashboard.api import create_app

async def build_app():
    s=get_settings(); pool=await asyncpg.create_pool(s.postgres_dsn,min_size=1,max_size=10)
    return create_app(pool=pool,redis_url=s.redis_url)

def main():
    s=get_settings(); app=asyncio.run(build_app()); uvicorn.run(app,host="0.0.0.0",port=8000,log_level=s.log_level.lower())

if __name__=="__main__": main()
