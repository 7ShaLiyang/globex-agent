import asyncio
import pytest
from app.composition import Container
from app.infrastructure.settings import Settings
from app.domain.models import ShoppingContext,BusinessError

@pytest.fixture
async def c(tmp_path):
    c=Container(Settings(database_url=f'sqlite+aiosqlite:///{tmp_path}/test.db',app_mode='demo',redis_url='',qdrant_url=''))
    await c.start();yield c;await c.close()

def ctx(buyer='alice'): return ShoppingContext(buyer,'session','job')
async def proposal(c,buyer='alice',pid='p01',qty=1):
    await c.commerce.perform(ctx(buyer),'cart_set',{'product_id':pid,'quantity':qty},'cart')
    return await c.commerce.perform(ctx(buyer),'order_propose',{},'proposal')

async def test_duplicate_order_and_cancel(c):
    p=await proposal(c)
    args={'proposal_id':p['id']}
    a,b=await asyncio.gather(c.commerce.perform(ctx(),'confirm',args,'confirm'),c.commerce.perform(ctx(),'confirm',args,'confirm'))
    assert a==b
    s=await c.commerce.snapshot(ctx());assert len(s['orders'])==1
    p2=await c.commerce.perform(ctx(),'order_cancel',{'order_id':a['order_id']},'cancel')
    await c.commerce.perform(ctx(),'confirm',{'proposal_id':p2['id']},'cancel-confirm')
    await c.commerce.perform(ctx(),'confirm',{'proposal_id':p2['id']},'cancel-confirm-again')
    assert (await c.search.products())[0]['stock']==18

async def test_isolation_and_conflicting_key(c):
    p=await proposal(c)
    with pytest.raises(BusinessError): await c.commerce.perform(ctx('bob'),'confirm',{'proposal_id':p['id']},'confirm')
    assert (await c.commerce.snapshot(ctx('bob')))['orders']==[]
    with pytest.raises(BusinessError): await c.commerce.perform(ctx(),'cart_set',{'product_id':'p02','quantity':1},'cart')

async def test_cart_revision_and_preference_confirmation(c):
    p=await proposal(c)
    await c.commerce.perform(ctx(),'cart_set',{'product_id':'p02','quantity':1},'cart2')
    with pytest.raises(BusinessError): await c.commerce.perform(ctx(),'confirm',{'proposal_id':p['id']},'confirm')
    p=await c.commerce.perform(ctx(),'preference_propose',{'key':'style','value':'简约'},'pref')
    assert (await c.commerce.snapshot(ctx()))['preferences']==[]
    await c.commerce.perform(ctx(),'confirm',{'proposal_id':p['id']},'pref-confirm')
    assert (await c.commerce.snapshot(ctx()))['preferences'][0]['value']=='简约'

async def test_stock_race(c):
    async with c.db.transaction() as u:
        p=await u.get('products','p01','*');p['stock']=1;await u.put('products','p01','*',p)
    a,b=await proposal(c,'alice'),await proposal(c,'bob')
    results=await asyncio.gather(c.commerce.perform(ctx(),'confirm',{'proposal_id':a['id']},'a'),c.commerce.perform(ctx('bob'),'confirm',{'proposal_id':b['id']},'b'),return_exceptions=True)
    assert sum(isinstance(r,BusinessError) for r in results)==1
    assert (await c.search.products())[0]['stock']==0

async def test_fallback(c):
    r=await c.search.search('headphones');assert r['mode']=='keyword_2gram';assert r['products'][0]['id'] in ['p01','p07']
    assert (await c.search.web('最新关税'))['available'] is False
