from app.domain.ports import AgentRuntime
from app.domain.models import ShoppingContext

class MainAgent:
    name = 'CommerceConcierge'
    def __init__(self, runtime: AgentRuntime): self.runtime = runtime
    async def run(self, ctx: ShoppingContext, text: str, state: dict | None = None):
        return await self.runtime.run(ctx, text, state)
