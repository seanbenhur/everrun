class TTLCache:
    """A small time-to-live cache."""

    def __init__(self, capacity, ttl_seconds, clock=None):
        raise NotImplementedError

    def set(self, key, value):
        raise NotImplementedError

    def get(self, key, default=None):
        raise NotImplementedError

    def delete(self, key):
        raise NotImplementedError

    def __contains__(self, key):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError
