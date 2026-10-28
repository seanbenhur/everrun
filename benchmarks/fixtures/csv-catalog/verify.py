import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from catalog import CatalogError, parse_catalog

products = parse_catalog(
    'stock,name,sku,price\n'
    '2,"Widget, large",ABC-1, 12.50 \n'
    '\n'
    '0,Small part,abc-2,0\n'
)
assert products == [
    {"sku": "ABC-1", "name": "Widget, large", "price": Decimal("12.50"), "stock": 2},
    {"sku": "abc-2", "name": "Small part", "price": Decimal("0"), "stock": 0},
]
assert parse_catalog(" \n\t\n") == []

invalid = [
    ("sku,name,price\na,b,1\n", "header"),
    ("sku,name,price,sku\na,b,1,c\n", "header"),
    ("sku,name,price,stock\n,b,1,2\n", "sku"),
    ("sku,name,price,stock\na, ,1,2\n", "name"),
    ("sku,name,price,stock\na,b,nope,2\n", "price"),
    ("sku,name,price,stock\na,b,-1,2\n", "price"),
    ("sku,name,price,stock\na,b,1,nope\n", "stock"),
    ("sku,name,price,stock\na,b,1,-1\n", "stock"),
    ("sku,name,price,stock\nA,b,1,2\na,c,1,2\n", "duplicate"),
]
for csv_text, message_fragment in invalid:
    try:
        parse_catalog(csv_text)
    except CatalogError as exc:
        message = str(exc).lower()
        assert message_fragment in message, (message_fragment, message)
        assert "line" in message, f"error should identify a source line: {message}"
    else:
        raise AssertionError(f"invalid catalog should fail: {csv_text!r}")

print("PASS: reordered CSV, quoted fields, whitespace, Decimal, blank input, and validation errors")
