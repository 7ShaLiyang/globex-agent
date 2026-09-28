import asyncio
from app.composition import Container
async def main():
    c=Container();await c.start()
    try:
        print(await c.search.index())
        from app.infrastructure.knowledge import ingest
        print(await ingest(c.settings,c.cache))
    finally: await c.close()
if __name__=='__main__': asyncio.run(main())
