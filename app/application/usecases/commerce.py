"""All mutations + their audit events + idempotency results commit together."""
import hashlib
import json
import time
import uuid
from app.domain.models import BusinessError, ShoppingContext, Order, OrderStatus, quote
from app.domain.ports import Repository, SearchPort

class Commerce:
    def __init__(self, repo: Repository, search: SearchPort):
        self.repo, self.search_port = repo, search

    async def perform(self, ctx: ShoppingContext, name: str, args: dict, key: str) -> dict:
        if not key or len(key) > 160:
            raise BusinessError('缺少或超长幂等键')
        digest = hashlib.sha256(json.dumps([name, args], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        identity = hashlib.sha256((ctx.buyer_id + ':' + key).encode()).hexdigest()
        async with self.repo.transaction() as u:
            if name in {'cart_get', 'orders_get', 'preferences_get'}:
                result=await self._execute(u,ctx,name,args)
                await u.event(ctx,name,{'args':args,'result':result})
                return result
            prior = await u.get('idempotency', identity, ctx.buyer_id)
            if prior:
                if prior['digest'] != digest:
                    raise BusinessError('同一幂等键不能用于不同请求')
                return prior['result']
            result = await self._execute(u, ctx, name, args)
            await u.put('idempotency', identity, ctx.buyer_id, {'digest': digest, 'result': result})
            await u.event(ctx, name, {'args': args, 'result': result})
            return result

    async def _execute(self, u, ctx, name, a):
        buyer = ctx.buyer_id
        if name == 'cart_set':
            pid, qty = str(a['product_id']), a['quantity']
            if isinstance(qty, bool) or not isinstance(qty, int) or not 0 <= qty <= 20:
                raise BusinessError('数量须为 0–20，0 表示移除')
            p = await u.get('products', pid, '*')
            if not p or qty > p['stock']:
                raise BusinessError('商品不存在或库存不足')
            cart = await u.get('carts', buyer, buyer) or {'id': buyer, 'items': {}, 'revision': 0}
            if qty: cart['items'][pid] = qty
            else: cart['items'].pop(pid, None)
            cart['revision'] += 1
            await u.put('carts', buyer, buyer, cart)
            return cart
        if name == 'cart_get':
            cart = await u.get('carts', buyer, buyer) or {'id': buyer, 'items': {}, 'revision': 0}
            rows = []
            for pid, qty in cart['items'].items():
                p = await u.get('products', pid, '*')
                if p: rows.append({**p, 'quantity': qty})
            return {**cart, 'products': rows}
        if name == 'order_propose':
            cart = await self._execute(u, ctx, 'cart_get', {})
            items = cart['products']
            pricing = quote(items, a.get('destination', 'US'), a.get('currency', 'USD'))
            proposal = {'id': str(uuid.uuid4()), 'kind': 'order', 'status': 'pending',
                        'items': items, 'cart_revision': cart['revision'], 'quote': pricing,
                        'expires_at': time.time()+900}
            await u.put('confirmations', proposal['id'], buyer, proposal)
            return proposal
        if name == 'preference_propose':
            key, value = str(a['key']).strip(), str(a['value']).strip()
            if key not in {'budget', 'brand', 'category', 'currency', 'destination', 'style'} or not 1 <= len(value) <= 200:
                raise BusinessError('不支持的偏好字段或内容过长')
            proposal = dict(id=str(uuid.uuid4()), kind='preference', key=key, value=value,
                            status='pending', expires_at=time.time()+900)
            await u.put('confirmations', proposal['id'], buyer, proposal)
            return proposal
        if name in ('confirm', 'reject'):
            p = await u.get('confirmations', a['proposal_id'], buyer)
            if not p: raise BusinessError('确认项不存在')
            if p['status'] != 'pending': return p
            if p['expires_at'] < time.time(): raise BusinessError('确认已过期，请重新发起')
            if name == 'reject':
                p['status'] = 'rejected'
            elif p['kind'] == 'preference':
                await u.put('preferences', p['key'], buyer, {'id': p['key'], 'value': p['value']})
                p['status'] = 'confirmed'
            elif p['kind'] == 'cancel_order':
                order = await u.get('orders', p['order_id'], buyer)
                if not order: raise BusinessError('订单不存在')
                entity = Order(OrderStatus(order['status'])); entity.cancel()
                if order['status'] != 'cancelled':
                    for item in order['items']:
                        product = await u.get('products', item['id'], '*')
                        product['stock'] += item['quantity']
                        await u.put('products', product['id'], '*', product)
                order['status'] = entity.status.value
                await u.put('orders', order['id'], buyer, order)
                p.update(status='confirmed', order_id=order['id'])
            elif p['kind'] == 'order':
                cart = await u.get('carts', buyer, buyer)
                if not cart or cart['revision'] != p['cart_revision']:
                    raise BusinessError('购物车已经变化，请重新获取报价')
                for item in p['items']:
                    product = await u.get('products', item['id'], '*')
                    if not product or product['stock'] < item['quantity'] or product['price'] != item['price']:
                        raise BusinessError('价格或库存已变化，请重新获取报价')
                    product['stock'] -= item['quantity']
                    await u.put('products', product['id'], '*', product)
                order = {'id': str(uuid.uuid4()), 'status': 'created', 'items': p['items'],
                         'quote': p['quote'], 'created_at': time.time()}
                await u.put('orders', order['id'], buyer, order)
                await u.put('carts', buyer, buyer, {'id': buyer, 'items': {}, 'revision': cart['revision']+1})
                p.update(status='confirmed', order_id=order['id'])
            await u.put('confirmations', p['id'], buyer, p)
            return p
        if name == 'order_cancel':
            order = await u.get('orders', a['order_id'], buyer)
            if not order: raise BusinessError('订单不存在')
            if order['status'] == 'cancelled': return order
            Order(OrderStatus(order['status'])).cancel()
            p = dict(id=str(uuid.uuid4()), kind='cancel_order', order_id=order['id'],
                     status='pending', expires_at=time.time()+900)
            await u.put('confirmations', p['id'], buyer, p)
            return p
        if name == 'orders_get': return {'orders': await u.list('orders', buyer)}
        if name == 'preferences_get': return {'preferences': await u.list('preferences', buyer)}
        raise BusinessError('未知操作')

    async def snapshot(self, ctx):
        async with self.repo.transaction() as u:
            return {'cart': await self._execute(u, ctx, 'cart_get', {}),
                    'orders': await u.list('orders', ctx.buyer_id),
                    'preferences': await u.list('preferences', ctx.buyer_id),
                    'confirmations': [p for p in await u.list('confirmations', ctx.buyer_id)
                                      if p['status'] == 'pending' and p['expires_at'] > time.time()]}
