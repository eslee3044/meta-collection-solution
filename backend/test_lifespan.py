import asyncio
from app.main import app, lifespan

async def run():
    async with lifespan(app):
        print("Lifespan setup completed successfully")

asyncio.run(run())
