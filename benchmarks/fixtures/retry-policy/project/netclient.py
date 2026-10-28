class Client:
    """Minimal HTTP client used by the retry-policy benchmark."""

    def __init__(self, transport):
        self.transport = transport

    def send(self, method, url):
        return self.transport.request(method, url)
