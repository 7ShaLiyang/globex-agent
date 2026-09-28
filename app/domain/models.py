"""Pure domain: no framework, database or network imports."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum

class BusinessError(ValueError):
    pass

@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str = 'USD'
    def __post_init__(self):
        if not self.amount.is_finite() or self.amount < 0:
            raise BusinessError('金额必须是有限非负数')
    def text(self):
        return str(self.amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))

@dataclass(frozen=True)
class Sku:
    id: str
    stock: int

@dataclass(frozen=True)
class Product:
    id: str
    title: str
    price: Money
    sku: Sku

@dataclass(frozen=True)
class ShoppingContext:
    buyer_id: str
    session_id: str
    job_id: str
    worker_id: str = ""

class OrderStatus(StrEnum):
    CREATED = 'created'
    CANCELLED = 'cancelled'
    SHIPPED = 'shipped'

@dataclass
class Order:
    status: OrderStatus
    def cancel(self):
        if self.status == OrderStatus.SHIPPED:
            raise BusinessError('已发货订单不能取消')
        self.status = OrderStatus.CANCELLED

# Teaching fixtures only. Not a live FX feed or actual customs schedule.
FX = {'USD': Decimal('1'), 'CNY': Decimal('7.10'), 'EUR': Decimal('.92')}
DESTINATIONS = {'US': (Decimal('.08'), Decimal('8')), 'CN': (Decimal('.13'), Decimal('12')), 'DE': (Decimal('.19'), Decimal('10'))}

def quote(items: list[dict], destination: str, currency: str = 'USD') -> dict:
    if destination not in DESTINATIONS or currency not in FX:
        raise BusinessError('仅支持目的地 US/CN/DE 和货币 USD/CNY/EUR')
    if not items:
        raise BusinessError('购物车为空')
    subtotal = Decimal('0')
    for item in items:
        qty = item['quantity']
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 20:
            raise BusinessError('单个商品数量须为 1–20')
        subtotal += Decimal(item['price']) * qty
    rate, shipping = DESTINATIONS[destination]
    tax = (subtotal * rate).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    def fmt(x): return Money(x * FX[currency], currency).text()
    return dict(subtotal=fmt(subtotal), tax=fmt(tax), shipping=fmt(shipping),
                total=fmt(subtotal + tax + shipping), currency=currency,
                destination=destination, estimated=True, rule_version='demo-2026-09',
                notice='教学估算：非真实税率/汇率；不包含实际清关、付款及物流。')
