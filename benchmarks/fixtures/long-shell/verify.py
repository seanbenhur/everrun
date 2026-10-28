import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
build = root / "build"
log = build / "invocations.log"
output = build / "index.json"
assert log.exists(), "the long-running shell tool was not invoked"
assert len(log.read_text(encoding="utf-8").splitlines()) == 1, "shell side effect was replayed"
assert output.exists(), "long-running tool did not finish producing its output"
records = json.loads(output.read_text(encoding="utf-8"))
expected = [
    {"id": f"item-{phase:03d}", "checksum": f"sha256:fixture-{phase:03d}"}
    for phase in range(1, 9)
]
assert records == expected, records
print("PASS: long shell task completed once with all eight indexed records")
