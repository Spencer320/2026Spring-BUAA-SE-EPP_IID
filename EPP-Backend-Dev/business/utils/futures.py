import warnings
import sys

if sys.version_info < (3, 13):

    def deprecated(messages: str | None = None):
        def wrapper(func):
            def inner(*args, **kwargs):
                if messages is None:
                    msg = f"Call to deprecated function {func.__name__}."
                else:
                    msg = messages
                warnings.warn(msg, category=DeprecationWarning)
                return func(*args, **kwargs)

            return inner

        return wrapper

else:
    from warnings import deprecated
