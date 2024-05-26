from opts.logopt import *
from opts.argsopt import *
from prometheus_client import Gauge, generate_latest
from .component import Component
import threading


class MEM(Component):
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

    @property
    def name(self) -> str:
        return self._metric

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
        self._lock = threading.RLock()
        self._enabled = get_arg(f"{self._metric}_enable")
        self._mem_bytes = Gauge(
            f"{self._metric}_bytes", "Memory usage in bytes.", ["type"]
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def get_attrs(self, argl):
        pass

    @enabled
    @locked
    def update(self) -> bytes:
        output = bytes("", "utf-8")
        mems = {}
        # use /proc/meminfo to get memory info
        with open("/proc/meminfo", "r") as f:
            for line in f.readlines():
                line = line.strip().split(sep=":", maxsplit=1)
                mems[line[0]] = (
                    float(line[1].strip().split(sep=" ", maxsplit=1)[0]) * 1024
                )
        self._mem_bytes.labels(type="memtotal").set(mems["MemTotal"])
        self._mem_bytes.labels(type="memfree").set(mems["MemFree"])
        self._mem_bytes.labels(type="memavailable").set(mems["MemAvailable"])
        self._mem_bytes.labels(type="buffers").set(mems["Buffers"])
        self._mem_bytes.labels(type="cached").set(mems["Cached"])
        self._mem_bytes.labels(type="slab").set(mems["Slab"])
        self._mem_bytes.labels(type="pagetables").set(mems["PageTables"])
        self._mem_bytes.labels(type="swapcached").set(mems["SwapCached"])
        self._mem_bytes.labels(type="swaptotal").set(mems["SwapTotal"])
        self._mem_bytes.labels(type="swapfree").set(mems["SwapFree"])
        self._mem_bytes.labels(type="hardwarecorrupted").set(mems["HardwareCorrupted"])
        output += generate_latest(self._mem_bytes)
        return output

    @enabled
    @locked
    def control(self, argl):
        raise NotImplementedError("Control for memory not implemented")
