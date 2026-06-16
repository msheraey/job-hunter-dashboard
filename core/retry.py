"""
core/retry.py — Retry infrastructure: exponential backoff + jitter + circuit breaker.
Transient failures are normal at scale; this turns them into non-events.
"""
import time
import random
import threading

import config

try:
    import redis as _redis_lib
except ImportError:
    _redis_lib = None


class RateLimitError(Exception):
    """A provider responded 429. Distinct from a real outage — callers should
    move on to the next provider without tripping its circuit breaker."""


class CircuitBreaker:
    """
    After `threshold` consecutive failures, the circuit OPENS for `cooldown` seconds:
    callers skip this provider instantly instead of waiting on timeouts.
    One success closes it again.

    State is shared across workers via Redis when config.REDIS_URL is set;
    otherwise it falls back to this process's in-memory state.
    """
    def __init__(self, name, threshold=4, cooldown=120):
        self.name = name
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.open_until = 0.0
        self._lock = threading.RLock()
        self._redis = None
        if config.REDIS_URL and _redis_lib:
            try:
                client = _redis_lib.from_url(
                    config.REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
                client.ping()
                self._redis = client
            except Exception as e:
                print(f"  ⚠️ Redis unavailable for breaker '{name}', using in-memory state: {str(e)[:80]}")

    def _key(self, suffix):
        return f"breaker:{self.name}:{suffix}"

    def is_open(self):
        if self._redis:
            try:
                open_until = float(self._redis.get(self._key("open_until")) or 0)
                return time.time() < open_until
            except Exception:
                pass  # fall through to in-memory state on Redis error
        with self._lock:
            return time.time() < self.open_until

    def record_success(self):
        if self._redis:
            try:
                self._redis.delete(self._key("failures"), self._key("open_until"))
                return
            except Exception:
                pass
        with self._lock:
            self.failures = 0
            self.open_until = 0.0

    def record_failure(self):
        if self._redis:
            try:
                key = self._key("failures")
                failures = self._redis.incr(key)
                if failures == 1:
                    self._redis.expire(key, 3600)
                if failures >= self.threshold:
                    self._redis.set(self._key("open_until"), time.time() + self.cooldown,
                                    ex=self.cooldown + 10)
                    print(f"  ⛔ Circuit OPEN for {self.name} — skipping for {self.cooldown}s")
                return
            except Exception:
                pass
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
