import time
from sqlalchemy import text
import pytest
from app.composition import Container
from app.infrastructure.settings import Settings
from app.domain.models import ShoppingContext

async def test_outbox_fifo_reclaim_and_fence(tmp_path):
    c=Container(Settings(database_url=f'sqlite+aiosqlite:///{tmp_path}/queue.db',app_mode='demo',redis_url='',qdrant_url=''))
    await c.start()
    try:
        async with c.db.transaction() as u: await u.put('sessions','s','b',{'id':'s','title':'test','state':None})
        a=await c.jobs.submit('b','s','耳机','first-message')
        b=await c.jobs.submit('b','s','背包','second-message')
        first=await c.jobs.claim(b['id']);assert first['id']==a['id']
        assert await c.jobs.claim() is None
        async with c.db.transaction() as u:
            await u.conn.execute(text('UPDATE jobs SET lease=:t WHERE id=:i'),{'t':time.time()-1,'i':a['id']})
        old=c.jobs.worker_id;c.jobs.worker_id='replacement'
        reclaimed=await c.jobs.claim();assert reclaimed['id']==a['id'];assert reclaimed['attempts']==2
        with pytest.raises(RuntimeError):
            await c.commerce.perform(ShoppingContext('b','s',a['id'],old),'cart_set',{'product_id':'p01','quantity':1},'old-worker')
        assert (await c.commerce.snapshot(ShoppingContext('b','s','ui')))['cart']['items']=={}
        await c.jobs.execute(reclaimed)
        second=await c.jobs.claim();assert second['id']==b['id']
        await c.jobs.execute(second)
        assert (await c.jobs.get('b',b['id']))['status']=='done'
    finally: await c.close()
