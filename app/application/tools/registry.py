import hashlib
import json
from app.domain.models import ShoppingContext, BusinessError

class BusinessTools:
    """No SDK types leak into this layer. Identity is never accepted from the model."""
    def __init__(self, commerce, ctx: ShoppingContext):
        self.commerce, self.ctx = commerce, ctx
    async def call(self, name: str, args: dict):
        raw = json.dumps([name,args], sort_keys=True, ensure_ascii=False)
        key = self.ctx.job_id + ':' + hashlib.sha256(raw.encode()).hexdigest()
        try:
            return await self.commerce.perform(self.ctx, name, args, key)
        except BusinessError as e:
            return {'error': str(e)}
