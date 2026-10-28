import importlib.util
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location(
    "inventory_case", root / "__init__.py", submodule_search_locations=[str(root)]
)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert hasattr(module, "available_products"), "package root must export available_products"

products = [
    {"name": "Zebra", "active": True, "stock": 2, "metadata": {"tags": ["original"]}},
    {"name": "ßeta", "active": True, "stock": 1, "metadata": {"tags": ["unicode"]}},
    {"name": "Hidden", "active": False, "stock": 9, "metadata": {"tags": []}},
    {"name": "Empty", "active": True, "stock": 0, "metadata": {"tags": []}},
]
before = [{**item, "metadata": {"tags": list(item["metadata"]["tags"])}} for item in products]
result = module.available_products(products)
assert [item["name"] for item in result] == ["ßeta", "Zebra"], result
assert result[0] is not products[1]
result[0]["metadata"]["tags"].append("changed")
assert products == before, "mutating returned nested data must not mutate input"
assert len(products) == 4, "input list must not be changed"
print("PASS: preserved pre-compaction casefold and recursive-copy requirements")
