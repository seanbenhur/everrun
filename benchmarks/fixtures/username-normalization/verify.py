import sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from usernames import normalize_username

cases = {
    None: None,
    "": None,
    "  \t": None,
    " Alice ": "alice",
    "0": "0",
    "  User-42\n": "user-42",
    42: None,
}
for value, expected in cases.items():
    actual = normalize_username(value)
    assert actual == expected, f"{value!r}: expected {expected!r}, got {actual!r}"
print(f"PASS: {len(cases)} username normalization cases")
