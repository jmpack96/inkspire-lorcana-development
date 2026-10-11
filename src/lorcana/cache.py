"""One-entry, bounded caches for expensive read-only command results."""
from copy import deepcopy
from threading import Lock
from time import monotonic


class ReadCache:
    def __init__(self, seconds=60, clock=monotonic):
        self.seconds, self.clock = seconds, clock
        self.lock = Lock()
        self.key, self.value, self.expires = None, None, 0

    def get(self, key, build):
        # Serialize misses so simultaneous Discord requests share one query.
        with self.lock:
            if self.value is None or self.key != key or self.clock() >= self.expires:
                value = build()  # Failed builds are never cached.
                self.key, self.value = key, deepcopy(value)
                self.expires = self.clock() + self.seconds
            return deepcopy(self.value)
