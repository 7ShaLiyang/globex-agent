from decimal import Decimal
import pytest
from app.domain.models import Money,Order,OrderStatus,quote,BusinessError

def test_money_and_quote():
    assert Money(Decimal('1.235')).text()=='1.24'
    q=quote([{'price':'79.00','quantity':2}],'US')
    assert q['total']=='178.64'
    assert q['estimated'] is True
    with pytest.raises(BusinessError): Money(Decimal('NaN'))
    with pytest.raises(BusinessError): quote([],'US')
    with pytest.raises(BusinessError): quote([{'price':'1','quantity':-1}],'US')
    with pytest.raises(BusinessError): quote([{'price':'1','quantity':True}],'US')

def test_order_state_machine():
    o=Order(OrderStatus.CREATED);o.cancel();o.cancel();assert o.status==OrderStatus.CANCELLED
    with pytest.raises(BusinessError): Order(OrderStatus.SHIPPED).cancel()

def test_layers():
    import ast
    from pathlib import Path
    for folder in ['domain','application']:
        for path in Path('app',folder).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom) and node.module:
                    assert not node.module.startswith(('agentscope','sqlalchemy','fastapi','redis','app.infrastructure','app.presentation','app.composition'))
                    if folder=='domain': assert not node.module.startswith('app.application')
