import importlib.util
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root.parent))
spec = importlib.util.spec_from_file_location("inventory_case", root / "__init__.py", submodule_search_locations=[str(root)])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert hasattr(module, "available_products"), "package root must export available_products"
products = [
    {"name": "zebra", "active": True, "stock": 2},
    {"name": "Alpha", "active": True, "stock": 1},
    {"name": "Hidden", "active": False, "stock": 9},
    {"name": "Empty", "active": True, "stock": 0},
]
before = [item.copy() for item in products]
result = module.available_products(products)
assert [item["name"] for item in result] == ["Alpha", "zebra"], result
assert result[0] is not products[1], "results must use fresh dictionaries"
result[0]["name"] = "changed"
assert products == before, "input list and dictionaries must remain unchanged"
print("PASS: inventory filtering, case-insensitive sorting, package export, and copy semantics")
