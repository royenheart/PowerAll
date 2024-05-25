from opts.logopt import *
from opts.argsopt import *
from prometheus_client import Gauge, Info, generate_latest


class MEM:
    def __init__(self) -> None:
        self._metric = "mem"

    def __enter__(self):
        add_option(
            f"--{self._metric}-enable",
            type=bool,
            default=True,
            help=f"Enable {self._metric} Component",
        )
        return self

    def enabled(f):
        def wrap(*args, **kwargs):
            self = args[0]
            if self._enabled:
                return f(*args, **kwargs)
            else:
                return None

        return wrap

    def locked(f):
        """locked

        In Flask 2.2.5, use threading model. See:
        https://superfastpython.com/thread-local-data/
        https://flask.palletsprojects.com/en/2.1.x/advanced_foreword/

        Args:
            f (_type_): _description_
        """

        def wrap(*args, **kwargs):
            self = args[0]
            with self._lock:
                return f(*args, **kwargs)

        return wrap

    def setup(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def get_attrs(self, argl):
        pass

    @enabled
    @locked
    def update(self) -> bytes:
        pass

    @enabled
    @locked
    def control(self, argl):
        raise NotImplementedError("Control for memory not implemented")
