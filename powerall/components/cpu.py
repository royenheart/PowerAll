from opts.logopt import *
from opts.argsopt import *
from prometheus_client import Gauge, Info, generate_latest
import os
import re
import threading
import psutil

cpus_list = re.compile(r"[0-9]+-[0-9]+")
cpufreq_sysfsp = "/sys/devices/system/cpu/"
cpufreq_policys = f"{cpufreq_sysfsp}/cpufreq/"
# https://man7.org/linux/man-pages/man5/proc.5.html
user_hz = 100.0


class CPU:
    def __init__(self) -> None:
        self._metric = "cpu"

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
        self._lock = threading.RLock()
        self._enabled = get_arg(f"{self._metric}_enable")
        self._cpu_nums = os.cpu_count()
        self._freqs = Gauge(
            f"{self._metric}_freqs", "CPU Freqs in MHz", ["cpu", "mode"]
        )
        self._utils = Gauge(f"{self._metric}_utils", "CPU Utils in percentage", ["cpu"])
        self._scaling_govs = Info(
            f"{self._metric}_scaling_govs", "Current Scaling Governors", ["cpu"]
        )
        self._cpu_seconds_total = Gauge(
            f"{self._metric}_seconds_total",
            "Seconds the CPUs spent in each mode.",
            ["cpu", "mode"],
        )
        self._loadavg = Gauge(f"{self._metric}_loadavg", "load average", ["m"])

        # get CPUFreq scaling drivers, available scaling governors and available scaling frequencies
        # use sysfs provided by CPUFreq module
        with open(f"{cpufreq_sysfsp}/cpu0/cpufreq/scaling_driver", "r") as f:
            self._scaling_driver = f.readline().strip()
        with open(
            f"{cpufreq_sysfsp}/cpu0/cpufreq/scaling_available_governors", "r"
        ) as f:
            self._scaling_available_governors = f.readline().strip().split()
        ava_freqs = f"{cpufreq_sysfsp}/cpu0/cpufreq/scaling_available_frequencies"
        if os.path.exists(ava_freqs):
            with open(ava_freqs, "r") as f:
                self._scaling_available_frequencies = f.readline().strip().split()
        else:
            self._scaling_available_frequencies = []

        # if exists, psutil will divide current by 1000 default
        self._cpu_freq_curr_div = 1.0
        if os.path.exists("/sys/devices/system/cpu/cpufreq/policy0") or os.path.exists(
            "/sys/devices/system/cpu/cpu0/cpufreq"
        ):
            self._cpu_freq_curr_div = 1000.0

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.warning("CPU component exit")

    def get_attrs(self, argl):
        attrs = {}
        for arg in argl:
            if arg == "cpufreqs":
                attrs["cpufreqs"] = {
                    "ava_governors": self._scaling_available_governors,
                    "ava_freqs": self._scaling_available_frequencies,
                    "cpunums": self._cpu_nums,
                }
        return attrs

    def cpufreqs_control(self, argl):
        result = {}
        argl_iter = iter(argl)
        while True:
            try:
                arg = next(argl_iter)
            except:
                break
            if arg == "change-gov":
                try:
                    cpus = next(argl_iter)
                    gov = next(argl_iter)
                except:
                    logger.warning("Change cpu gov command wrong!")
                    result["error"] = "cpu control failed"
                    return result
                gov = str(gov)
                if not gov in self._scaling_available_governors:
                    result["error"] = f"no chosen governors {gov}"
                    return result
                if cpus == "all":
                    for i in range(self._cpu_nums):
                        with open(
                            f"{cpufreq_sysfsp}/cpu{i}/cpufreq/scaling_governor", "wb"
                        ) as f:
                            f.write(gov.encode())
                else:
                    cpulist = self.parse_cpus(cpus)
                    if cpulist is None:
                        logger.warning(f"parse error: {str(argl)} Check your syntax")
                        result["error"] = "cpu change gov syntax error"
                        return result
                    cpulist = list(set(cpulist))
                    for c in cpulist:
                        with open(
                            f"{cpufreq_sysfsp}/cpu{c}/cpufreq/scaling_governor", "wb"
                        ) as f:
                            f.write(gov.encode())
            elif arg == "change-freq":
                try:
                    cpus = next(argl_iter)
                    freq = next(argl_iter)
                except:
                    logger.warning("Change cpu freq command wrong!")
                    result["error"] = "cpu control failed"
                    return result
                freq = str(freq)
                if (not freq in self._scaling_available_frequencies) or (
                    "userspace" not in self._scaling_available_governors
                ):
                    result["error"] = f"no chosen freq {freq} or gov userspace"
                    return result
                if cpus == "all":
                    for i in range(self._cpu_nums):
                        with open(
                            f"{cpufreq_sysfsp}/cpu{i}/cpufreq/scaling_governors", "wb"
                        ) as f:
                            f.write("userspace".encode())
                        with open(
                            f"{cpufreq_sysfsp}/cpu{i}/cpufreq/scaling_setspeed", "wb"
                        ) as f:
                            f.write(freq.encode())
                else:
                    cpulist = self.parse_cpus(cpus)
                    if cpulist is None:
                        logger.warning(f"parse error: {str(argl)} Check your syntax")
                        result["error"] = "cpu change freq syntax error"
                        return result
                    cpulist = list(set(cpulist))
                    for c in cpulist:
                        with open(
                            f"{cpufreq_sysfsp}/cpu{c}/cpufreq/scaling_governors", "wb"
                        ) as f:
                            f.write("userspace".encode())
                        with open(
                            f"{cpufreq_sysfsp}/cpu{c}/cpufreq/scaling_setspeed", "wb"
                        ) as f:
                            f.write(freq.encode())
            else:
                result["error"] = "unknown CPU control commands"
                return result
        result["success"] = "cpu control success"
        return result

    def parse_cpus(self, cpus: str) -> list:
        """CPU/CPU0,CPU1,...CPUx/CPU0-CPUx/CPU0-CPUx1/CPUx2-CPUx3

        Where all use index

        Args:
            cpus (str): _description_

        Returns:
            list: _description_
        """
        ret = []
        for i in cpus.split(","):
            if cpus_list.match(i):
                l, r = i.split("-")
                try:
                    l = int(l)
                    r = int(r)
                    ret.extend(range(l, r + 1))
                except:
                    return None
            else:
                try:
                    n = int(i)
                    ret.append(n)
                except:
                    return None
        return ret

    @enabled
    @locked
    def update(self) -> bytes:
        output = bytes("", "utf-8")
        freqs = psutil.cpu_freq(percpu=True)
        utils = psutil.cpu_percent(percpu=True)
        cputimes = {}
        with open(f"/proc/stat", "r") as f:
            for line in f.readlines():
                line = line.strip().split(sep=" ", maxsplit=1)
                cputimes[line[0]] = line[1].strip()
        # use /proc/loadavg to get load average
        with open("/proc/loadavg", "r") as f:
            avgs = f.readline().strip().split(sep=" ")
            self._loadavg.labels(m="1").set(avgs[0])
            self._loadavg.labels(m="5").set(avgs[1])
            self._loadavg.labels(m="15").set(avgs[2])
        for c in range(self._cpu_nums):
            self._freqs.labels(cpu=c, mode="current").set(
                freqs[c][0] * self._cpu_freq_curr_div
            )
            self._freqs.labels(cpu=c, mode="min").set(freqs[c][1])
            self._freqs.labels(cpu=c, mode="max").set(freqs[c][2])
            self._utils.labels(cpu=c).set(utils[c])
            with open(f"{cpufreq_sysfsp}/cpu{c}/cpufreq/scaling_governor", "r") as f:
                scaling_driver = f.readline().strip()
                self._scaling_govs.labels(cpu=c).info({"governors": scaling_driver})
            # parse cpu time spent on each mode by /proc/stat
            cputime = cputimes[f"cpu{c}"].split(sep=" ")
            self._cpu_seconds_total.labels(cpu=c, mode="user").set(
                float(cputime[0]) / user_hz
            )
            self._cpu_seconds_total.labels(cpu=c, mode="nice").set(
                float(cputime[1]) / user_hz
            )
            self._cpu_seconds_total.labels(cpu=c, mode="system").set(
                float(cputime[2]) / user_hz
            )
            self._cpu_seconds_total.labels(cpu=c, mode="idle").set(
                float(cputime[3]) / user_hz
            )
            self._cpu_seconds_total.labels(cpu=c, mode="iowait").set(
                float(cputime[4]) / user_hz
            )
            self._cpu_seconds_total.labels(cpu=c, mode="irq").set(
                float(cputime[5]) / user_hz
            )
            self._cpu_seconds_total.labels(cpu=c, mode="softirq").set(
                float(cputime[6]) / user_hz
            )
            self._cpu_seconds_total.labels(cpu=c, mode="steal").set(
                float(cputime[7]) / user_hz
            )
        output += (
            generate_latest(self._freqs)
            + generate_latest(self._utils)
            + generate_latest(self._scaling_govs)
            + generate_latest(self._cpu_seconds_total)
            + generate_latest(self._loadavg)
        )
        return output

    @enabled
    @locked
    def control(self, argl):
        result = {}
        try:
            result = self.cpufreqs_control(argl)
            return result
        except Exception as e:
            logger.warning(f"CPUFreq control failed due to: {e}")
            result["error"] = "cpufreq control failed"
        return result
