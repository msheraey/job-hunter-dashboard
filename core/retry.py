"""
core/retry.py — Retry infrastructure: exponential backoff + jitter + circuit breaker.
Transient failures are normal at scale; this turns them into non-events.
"""
import time
import random
import threading

class CircuitBreaker:
    """
    After `threshold` consecutive failures, the circuit OPENS for `cooldown` seconds:
    callers skip this provider instantly instead of waiting on timeouts.
    One success closes it again.
    """
    def __init__(self, name, threshold=4, cooldown=120):
        self.name = name
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.open_until = 0.0
        self._lock = threading.RLock()

    def is_open(self):
        with self._lock:
            return time.time() < self.open_until

    def record_success(self):
        with self._lock:
            self.failures = 0
            self.open_until = 0.0

    def record_failure(self):
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.open_until = time.time() + self.cooldown
                print(f"  ⛔ Circuit OPEN for {self.name} — skipping for {self.cooldown}s")

def backoff_sleep(attempt, base=1.5, cap=20.0):
    """Exponential backoff with full jitter: sleep U(0, min(cap, base*2^attempt))."""
    time.sleep(random.uniform(0, min(cap, base * (2 ** attempt))))

def with_retries(fn, attempts=3, on_fail=None, label="call"):
    """
    Run fn() up to `attempts` times with backoff+jitter between tries.
    Returns fn() result, or on_fail value after final failure (never raises).
    """
    last_err = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < attempts - 1:
                backoff_sleep(i)
    print(f"  ❌ {label} failed after {attempts} attempts: {last_err}")
    return on_fail
