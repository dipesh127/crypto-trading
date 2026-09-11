#!/usr/bin/env python3
import asyncio
from pathlib import Path
import asyncpg
from app.config import get_settings

async def main():
    s=get_settings(); pool=await asyncpg.create_pool(s.postgres_dsn)
    try:
        await pool.execute(Path('sql/002_execution.sql').read_text())
        await pool.execute(Path('sql/012_binance_data_layer.sql').read_text())
        print('execution schema ready')
    finally: await pool.close()
if __name__=='__main__': asyncio.run(main())
