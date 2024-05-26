from prometheus_client import Gauge, Info, generate_latest
from pynvml import *
from opts.logopt import *
from opts.argsopt import *
from .component import Component
import re
import threading

nvgpus_list = re.compile(r"[0-9]+-[0-9]+")


class NVGPU(Component):
    def __init__(self) -> None:
        self._metric = "nvgpu"

    def __enter__(self):
        add_option(
            f"--{self._metric}-enable",
            type=bool,
            default=True,
            help=f"Enable {self._metric} Component",
        )
        add_option(
            f"--{self._metric}-config",
            type=str,
            default="nvml",
            choices=["nvml"],
            help=f"Set GPU Control Subsystem",
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
        self._config = get_arg(f"{self._metric}_config")
        try:
            nvmlInit()
        except NVMLError as error:
            logger.warning(
                f"Could not init NVML: {error}, will disable nvgpu info collect"
            )
            self._enabled = False
        self._nvgpu_power = Gauge(
            f"{self._metric}_power",
            "NVGPU Power information from nvml (milliwatt).",
            ["index", "mode"],
        )
        self._nvgpu_fan_speed = Gauge(
            f"{self._metric}_fan_speed",
            "NVGPU Fan Speed from nvml. (rpm)",
            ["index", "fan", "mode"],
        )
        self.collect_gpu_stable_info()
        self._nvgpu_power_enforce_limits = [None] * self._nvgpu_nums
        self._nvgpu_clocks = [x for x in range(NVML_CLOCK_COUNT)]
        self._nvgpu_id_clocks = [x for x in range(NVML_CLOCK_ID_COUNT)]
        self._nvgpu_temps = [x for x in range(NVML_TEMPERATURE_COUNT)]
        # uuid, name, bus_type
        self._nvgpu_info = Info(
            f"{self._metric}_gpuinfo",
            "NVGPU information from nvml.",
            ["index"],
        )
        self._nvgpu_appclk = Gauge(
            f"{self._metric}_appclk",
            "NVGPU Applications Clock information from nvml. (MHz)",
            ["index", "type"],
        )
        self._nvgpu_clk = Gauge(
            f"{self._metric}_clk",
            "NVGPU Clock information from nvml. (MHz)",
            ["index", "type", "id"],
        )
        # mode
        self._nvgpu_compute_mode = Info(
            f"{self._metric}_compute_mode",
            "NVGPU Compute Mode information from nvml.",
            ["index"],
        )
        self._nvgpu_perf = Gauge(
            f"{self._metric}_perf",
            "NVGPU Performance State information from nvml. Value indicates P<value>",
            ["index"],
        )
        # mode
        self._nvgpu_persis_mode = Info(
            f"{self._metric}_persis_mode",
            "NVGPU Persistence Mode information from nvml.",
            ["index"],
        )
        self._nvgpu_util = Gauge(
            f"{self._metric}_util",
            "NVGPU Utilization Rates information from nvml. (percentage)",
            ["index", "type"],
        )
        self._nvgpu_temp = Gauge(
            f"{self._metric}_temp",
            "NVGPU Temperature information from nvml in Celsius format.",
            ["index", "type"],
        )
        self._nvgpu_mem = Gauge(
            f"{self._metric}_mem",
            "NVGPU Memory from nvml (bytes IEC).",
            ["index", "mode"],
        )

    @enabled
    def collect_gpu_stable_info(self):
        try:
            self._nvgpu_nums = nvmlDeviceGetCount()
            self._nvgpu_devices = []
            for i in range(self._nvgpu_nums):
                self._nvgpu_devices.append(nvmlDeviceGetHandleByIndex(i))
            # driver_v, cuda_v, nvml_v
            self._nvgpu_sys_info = Info(
                f"{self._metric}_sysinfo", "NVGPU System information from nvml."
            )
            cudaV = nvmlSystemGetCudaDriverVersion_v2()
            # Rounding
            self._nvgpu_sys_info.info(
                {
                    "driver_v": nvmlSystemGetDriverVersion(),
                    "cuda_v": f"{cudaV//1000}.{cudaV%1000//10}",
                    "nvml_v": nvmlSystemGetNVMLVersion(),
                }
            )
            self._nvgpu_has_fan = [True] * self._nvgpu_nums
            self._fanNums = [0] * self._nvgpu_nums
            self._nvgpu_power_min_maxs = []
            for i, d in enumerate(self._nvgpu_devices):
                fanNums = nvmlDeviceGetNumFans(d)
                self._fanNums[i] = fanNums
                if fanNums > 0:
                    minFanSpeed, maxFanSpeed = 0.0, 0.0
                    nvmlDeviceGetMinMaxFanSpeed(d, minFanSpeed, maxFanSpeed)
                    for f in range(fanNums):
                        self._nvgpu_fan_speed.labels(index=i, fan=f, mode="min").set(
                            minFanSpeed
                        )
                        self._nvgpu_fan_speed.labels(index=i, fan=f, mode="max").set(
                            maxFanSpeed
                        )
                else:
                    logger.warning(f"GPU {i} has not Fan. Will disable it")
                    self._nvgpu_has_fan[i] = False
                try:
                    nvgpu_power_min_max = nvmlDeviceGetPowerManagementLimitConstraints(
                        d
                    )
                    self._nvgpu_power.labels(index=i, mode="min").set(
                        nvgpu_power_min_max[0]
                    )
                    self._nvgpu_power.labels(index=i, mode="max").set(
                        nvgpu_power_min_max[1]
                    )
                    self._nvgpu_power_min_maxs.append(nvgpu_power_min_max)
                except NVMLError as error:
                    logger.warning(
                        f"unable to get GPU {i} Power Min/Max Limitation Value: {error}"
                    )
        except NVMLError as error:
            logger.warning(
                f"Could not collect NVGPU Info, have you insert NVGPU Card or installed Driver correctly?: {error}"
            )
            self._enabled = False

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            nvmlShutdown()
        except NVMLError as e:
            logger.warning(f"NVML {e}, no need to shutdown")
        except Exception as e:
            logger.warning(f"Occur {e} when exit NVGPU component")
        logger.warning("NVGPU component exit")

    def get_attrs(self, argl):
        attrs = {}
        for arg in argl:
            if arg == "plc":
                # Each GPU's Power Management Limit Constraints
                attrs["plc"] = self._nvgpu_power_min_maxs
            else:
                logger.warning(f"Unknown NVGPU get attr command: {arg}")
        return attrs

    def nvml_control(self, argl):
        result = {}
        argl_iter = iter(argl)
        while True:
            try:
                arg = next(argl_iter)
            except:
                break
            if arg == "change-pl":
                try:
                    index = next(argl_iter)
                    pl = next(argl_iter)
                except:
                    logger.warning("Change nvgpu powerlimit command wrong!")
                    result["error"] = "nvgpu control failed"
                    return result
                if index == "all":
                    for i, d in enumerate(self._nvgpu_devices):
                        try:
                            # use mW
                            nvmlDeviceSetPowerManagementLimit(d, int(pl) * 1000)
                        except NVMLError as e:
                            logger.warning(
                                f"Change NVGPU {i} change powerlimit to {pl} failed due to: {e}"
                            )
                            result["error"] = "nvgpu change pl failed"
                            return result
                else:
                    gpulist = self.parse_gpus(index)
                    if gpulist is None:
                        logger.warning(f"parse error: {str(argl)} Check your syntax")
                        result["error"] = "nvgpu change pl syntax error"
                        return result
                    gpulist = list(set(gpulist))
                    for g in gpulist:
                        try:
                            d = self._nvgpu_devices[g]
                            # use mW
                            nvmlDeviceSetPowerManagementLimit(d, int(pl) * 1000)
                        except NVMLError as e:
                            logger.warning(
                                f"Change NVGPU {g} change powerlimit to {pl} failed due to: {e}"
                            )
                            result["error"] = "nvgpu change pl failed"
                            return result
                        except IndexError as e:
                            logger.warning(f"Set invalid NVGPU index {g}")
                            result["error"] = "set nvgpu index out of range"
                            return result
            else:
                result["error"] = "unknown NVGPU control commands"
                return result
        result["success"] = "nvgpu control success"
        return result

    def parse_gpus(self, gpus: str) -> list:
        """GPU/GPU0,GPU1,...GPUx/GPU0-GPUx/GPU0-GPUx1/GPUx2-GPUx3

        Where all use index

        Args:
            gpus (str): _description_

        Returns:
            list: _description_
        """
        ret = []
        for i in gpus.split(","):
            if nvgpus_list.match(i):
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
        final_output = bytes("", "utf-8")
        final_output += generate_latest(self._nvgpu_sys_info)
        for i, d in enumerate(self._nvgpu_devices):
            # Get GPU Info

            uuid, name, busType = (
                nvmlDeviceGetUUID(d),
                nvmlDeviceGetName(d),
                getBusTypeString(nvmlDeviceGetBusType(d)),
            )
            self._nvgpu_info.labels(index=i).info(
                {"uuid": uuid, "name": name, "bus_type": busType}
            )
            final_output += generate_latest(self._nvgpu_info)

            # Get GPU Fan Info

            if self._nvgpu_has_fan[i]:
                for f in range(self._fanNums[i]):
                    fanSpeed = nvmlDeviceGetFanSpeed_v2(d, f)
                    self._nvgpu_fan_speed.labels(index=i, fan=f, mode="current").set(
                        fanSpeed
                    )
                final_output += generate_latest(self._nvgpu_fan_speed)

            # Get GPU Clock Info

            for t in self._nvgpu_clocks:
                try:
                    appclk = nvmlDeviceGetApplicationsClock(d, t)
                    self._nvgpu_appclk.labels(index=i, type=getClockTypeString(t)).set(
                        appclk
                    )
                except NVMLError as error:
                    logger.warning(
                        f"unable to get GPU {i} Applications Clock Type {getClockTypeString(t)} Info: {error}. Will disable it"
                    )
                    self._nvgpu_clocks.remove(t)
                for tt in self._nvgpu_id_clocks:
                    try:
                        clk = nvmlDeviceGetClock(d, t, tt)
                        self._nvgpu_clk.labels(
                            index=i, type=getClockTypeString(t), id=getClockIDString(tt)
                        ).set(clk)
                    except NVMLError as error:
                        logger.warning(
                            f"unable to get GPU {i} Clock Type {getClockTypeString(t)} ID {getClockIDString(tt)} Info: {error}. Will disable it"
                        )
                        self._nvgpu_id_clocks.remove(tt)
            final_output += generate_latest(self._nvgpu_appclk)
            final_output += generate_latest(self._nvgpu_clk)

            # Get Compute Mode

            try:
                compute_m = nvmlDeviceGetComputeMode(d)
                self._nvgpu_compute_mode.labels(index=i).info(
                    {"mode": getComputeModeString(compute_m)}
                )
            except NVMLError as error:
                logger.warning(f"unable to get GPU {i} Compute Mode Info: {error}")
            final_output += generate_latest(self._nvgpu_compute_mode)

            # Get Performance State

            try:
                perf_state = nvmlDeviceGetPerformanceState(d)
                self._nvgpu_perf.labels(index=i).set(perf_state)
            except NVMLError as error:
                return logger.warning(
                    f"unable to get GPU {i} Performance State Info: {error}"
                )
            final_output += generate_latest(self._nvgpu_perf)

            # Get Persistence Mode

            try:
                persis_mode = nvmlDeviceGetPersistenceMode(d)
                self._nvgpu_persis_mode.labels(index=i).info(
                    {"mode": getPersisModeString(persis_mode)}
                )
            except NVMLError as error:
                return logger.warning(
                    f"unable to get GPU {i} Persistence Mode Info: {error}"
                )
            final_output += generate_latest(self._nvgpu_persis_mode)

            # Get GPU Utilization

            try:
                util = nvmlDeviceGetUtilizationRates(d)
                self._nvgpu_util.labels(index=i, type="GPU").set(util.gpu)
                self._nvgpu_util.labels(index=i, type="MEMORY").set(util.memory)
            except NVMLError as error:
                return logger.warning(
                    f"unable to get GPU {i} Utilization Info: {error}"
                )
            final_output += generate_latest(self._nvgpu_util)

            # Get Temperature Info

            for t in self._nvgpu_temps:
                try:
                    temp = nvmlDeviceGetTemperature(d, t)
                    self._nvgpu_temp.labels(
                        index=i, type=getTemperatureSensorString(t)
                    ).set(temp)
                except NVMLError as error:
                    self._nvgpu_temps.remove(t)
                    return logger.warning(
                        f"unable to get GPU {i} Temperature Sensor {getTemperatureSensorString(t)} Value: {error}. Will disable it"
                    )
                final_output += generate_latest(self._nvgpu_temp)

            # Get Power Info

            try:
                power = nvmlDeviceGetPowerUsage(d)
                self._nvgpu_power.labels(index=i, mode="usage").set(power)
            except NVMLError as error:
                return logger.warning(
                    f"unable to get GPU {i} Power Usage Value: {error}"
                )
            try:
                enforce_limit = nvmlDeviceGetEnforcedPowerLimit(d)
                self._nvgpu_power_enforce_limits[i] = enforce_limit
                self._nvgpu_power.labels(index=i, mode="enforce_limit").set(
                    enforce_limit
                )
            except NVMLError as error:
                logger.warning(
                    f"unable to get GPU {i} Power Enforced Limitation Value: {error}"
                )
            final_output += generate_latest(self._nvgpu_power)

            """
                Get Memory Info
                GetMemoryInfo_v2() could not correctly show the memory info in some situation.
            """

            try:
                mem = nvmlDeviceGetMemoryInfo(d)
                self._nvgpu_mem.labels(index=i, mode="total").set(mem.total)
                self._nvgpu_mem.labels(index=i, mode="free").set(mem.free)
                self._nvgpu_mem.labels(index=i, mode="used").set(mem.used)
            except NVMLError as error:
                return logger.warning(f"unable to get GPU {i} Memory Info: {error}")
            final_output += generate_latest(self._nvgpu_mem)

        return final_output

    @enabled
    @locked
    def control(self, argl):
        result = {}
        if self._config == "nvml":
            result = self.nvml_control(argl)
        else:
            logger.warning("No NVGPU controls config choose")
            result = {"error": "No NVGPU config choose"}
        return result


def getBusTypeString(busT: c_uint) -> str:
    if busT == NVML_BUS_TYPE_AGP:
        return "AGP"
    elif busT == NVML_BUS_TYPE_FPCI:
        return "FPCI"
    elif busT == NVML_BUS_TYPE_PCI:
        return "PCI"
    elif busT == NVML_BUS_TYPE_PCIE:
        return "PCIE"
    elif busT == NVML_BUS_TYPE_UNKNOWN:
        return "UNKNOWN"
    else:
        return "UNKNOWN"


def getClockTypeString(typeN: c_uint) -> str:
    if typeN == NVML_CLOCK_GRAPHICS:
        return "GRAPHICS"
    elif typeN == NVML_CLOCK_SM:
        return "SM"
    elif typeN == NVML_CLOCK_MEM:
        return "MEM"
    elif typeN == NVML_CLOCK_VIDEO:
        return "VIDEO"
    else:
        return "UNKNOWN"


def getClockIDString(typeN: c_uint) -> str:
    if typeN == NVML_CLOCK_ID_CURRENT:
        return "CURRENT"
    elif typeN == NVML_CLOCK_ID_APP_CLOCK_TARGET:
        return "APP CLOCK TARGET"
    elif typeN == NVML_CLOCK_ID_APP_CLOCK_DEFAULT:
        return "APP CLOCK DEFAULT"
    elif typeN == NVML_CLOCK_ID_CUSTOMER_BOOST_MAX:
        return "CUSTOMER BOOST MAX"
    else:
        return "UNKNOWN"


def getComputeModeString(modeN: c_uint) -> str:
    if modeN == NVML_COMPUTEMODE_DEFAULT:
        return "DEFAULT"
    elif modeN == NVML_COMPUTEMODE_EXCLUSIVE_THREAD:
        return "EXCLUSIVE THREAD"
    elif modeN == NVML_COMPUTEMODE_PROHIBITED:
        return "PROHIBITED"
    elif modeN == NVML_COMPUTEMODE_EXCLUSIVE_PROCESS:
        return "EXCLUSIVE PROCESS"
    else:
        return "UNKNOWN"


def getPstatesString(stateN: c_uint) -> str:
    if NVML_PSTATE_UNKNOWN != stateN:
        return f"P{stateN}"
    else:
        return "UNKNOWN"


def getPersisModeString(stateN: c_uint) -> str:
    if stateN == NVML_FEATURE_DISABLED:
        return "OFF"
    else:
        return "ON"


def getTemperatureSensorString(tempN: c_uint) -> str:
    if tempN == NVML_TEMPERATURE_GPU:
        return "GPU"
    else:
        return "UNKNOWN"
