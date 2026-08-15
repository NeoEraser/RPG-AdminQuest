"""
Minimal shim implementing `splat` to satisfy imports from setuptools/_distutils.
This is a pragmatic workaround — a more correct fix is to resolve package versions.
"""
from functools import wraps


def splat(func):
    """Convert a function that takes multiple args into one that takes a single iterable arg.
    Example: @splat
def f(a,b): ...; f([1,2]) -> calls f(1,2)
    """
    @wraps(func)
    def wrapper(args, *rest, **kwargs):
        # if args is a sequence, expand it; otherwise pass as is
        try:
            # treat strings as single arg
            if isinstance(args, (list, tuple)):
                return func(*args, *rest, **kwargs)
        except Exception:
            pass
        return func(args, *rest, **kwargs)
    return wrapper
