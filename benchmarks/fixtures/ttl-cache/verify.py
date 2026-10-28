import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from cache import TTLCache

now = [0.0]
cache = TTLCache(2, 5, clock=lambda: now[0])
cache.set("a", 1)
cache.set("b", 2)
assert cache.get("a") == 1
cache.set("c", 3)
assert "b" not in cache, "reading a must make it more recent than b"
assert cache.get("a") == 1 and cache.get("c") == 3
cache.set("c", 30)
assert cache.get("c") == 30
assert cache.delete("c") is True
assert cache.delete("c") is False

cache.set("nullable", None)
assert "nullable" in cache and cache.get("nullable") is None

expiry = TTLCache(3, 5, clock=lambda: now[0])
expiry.set("short", "value")
now[0] = 4
assert expiry.get("short") == "value"
now[0] = 5
assert "short" not in expiry
assert len(expiry) == 0, "expired entries must not count toward length"

for args in ((0, 1), (-1, 1), (True, 1), (1, 0), (1, -1)):
    try:
        TTLCache(*args)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid constructor values should fail: {args!r}")

print("PASS: TTL expiration, fixed TTL on read, LRU eviction, update, None values, delete, and validation")
