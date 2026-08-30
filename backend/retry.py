"""Small retry-with-backoff helper shared by the pipeline's network-dependent steps.

Built after this project's own build process hit real, repeated transient network
failures (Homebrew's package index, Hugging Face downloads, a stale Groq model name)
— the pipeline itself had no retry logic for the same class of failure until now.
"""
import time


def retry_with_backoff(fn, *, attempts=3, base_delay=2.0, on_retry=None):
    """Call fn() up to `attempts` times, with exponential backoff between tries.
    Re-raises the last exception if all attempts fail. `on_retry(attempt, exc)` is
    called (if given) before each retry sleep, so callers can log what's happening.
    """
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < attempts:
                if on_retry:
                    on_retry(attempt, e)
                time.sleep(base_delay * attempt)
    raise last_exc
