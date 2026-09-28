import asyncio
import logging
from app.composition import Container
async def main():
    logging.basicConfig(level=logging.INFO)
    c=Container();await c.start()
    try: await c.jobs.loop()
    finally: await c.close()
if __name__=='__main__': asyncio.run(main())
