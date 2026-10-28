import importlib.util
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
spec = importlib.util.spec_from_file_location("netclient", root / "netclient.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class Response:
    def __init__(self, status_code):
        self.status_code = status_code


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url):
        self.calls.append((method, url))
        return next(self.responses)


delays = []
transport = Transport([Response(429), Response(503), Response(200)])
response = module.Client(transport, sleep=delays.append).send("GET", "/resource")
assert response.status_code == 200
assert len(transport.calls) == 3, transport.calls
assert delays == [0.1, 0.2], delays

delays = []
transport = Transport([Response(503) for _ in range(4)])
response = module.Client(transport, sleep=delays.append).send("GET", "/resource")
assert response.status_code == 503
assert len(transport.calls) == 4, transport.calls
assert delays == [0.1, 0.2, 0.2], delays

for method, status in (("POST", 503), ("GET", 404)):
    delays = []
    transport = Transport([Response(status)])
    response = module.Client(transport, sleep=delays.append).send(method, "/resource")
    assert response.status_code == status
    assert len(transport.calls) == 1, transport.calls
    assert delays == [], delays

print("PASS: clarification-driven retry policy, total attempts, backoff cap, and non-retry cases")
