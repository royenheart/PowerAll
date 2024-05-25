from opts.logopt import *
from opts.argsopt import *
from prometheus_client import Gauge, Info, generate_latest
from redfish import redfish_client
import threading
import re

fans_list = re.compile(r"[0-9]+-[0-9]+")


class BMC:
    def __init__(self) -> None:
        self._metric = "bmc"

    def __enter__(self):
        add_option(
            f"--{self._metric}-enable",
            type=bool,
            default=True,
            help=f"Enable {self._metric} Component",
        )
        add_option(
            f"--{self._metric}-host",
            type=str,
            default="127.0.0.1",
            help=f"Set BMC host address",
        )
        add_option(
            f"--{self._metric}-user",
            type=str,
            default="admin",
            help=f"Set BMC User, default will be admin",
        )
        add_option(
            f"--{self._metric}-passwd",
            type=str,
            default="admin",
            help=f"Set BMC User passwd, default will be admin",
        )
        add_option(
            f"--{self._metric}-config",
            type=str,
            default="Inspur-NF5280M6",
            choices=["Inspur-NF5280M6"],
            help=f"Set Manufacturer, determine some component's monitor/control methods. Will use Inspur-NF5280M6's config if not set, in this case some data will lose",
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
        self._enabled = get_arg(f"{self._metric}_enable")
        self._config = get_arg(f"{self._metric}_config")
        self._lock = threading.RLock()
        if self._enabled:
            # manufacturer, model
            self._machine_info = Info(
                f"{self._metric}_machine_info",
                "Machine info in BMC",
            )
            # state, health, controlmode, speedratio
            self._fan_info = Info(
                f"{self._metric}_fan_info",
                "Fan info in BMC",
                ["index", "name"],
            )
            # reading
            self._fan_read = Gauge(
                f"{self._metric}_fan_read",
                "Fan read value in BMC",
                ["index", "name", "readingunits"],
            )
            # cpupower, mempower, fanpower, totalpower
            self._power_info = Gauge(
                f"{self._metric}_power_info",
                "Power info in BMC",
                ["component"],
            )
            # poweroutputpower, powerinputpower,
            self._powersupply_power = Gauge(
                f"{self._metric}_powersupply_power",
                "PowerSupply info in BMC",
                ["index", "mode"],
            )
            # status
            self._threshold_sensors = Info(
                f"{self._metric}_threshold_sensors",
                "Threshold sensors info in BMC.",
                ["name", "unit"],
            )
            # readingvalue
            self._threshold_sensors_values = Gauge(
                f"{self._metric}_threshold_sensors_values",
                "Threshold sensors data in BMC. None value will set to -1",
                ["name", "unit"],
            )
            # status
            self._discrete_sensors = Gauge(
                f"{self._metric}_discrete_sensors",
                "Discrete sensors data in BMC. 0 is Disable, 1 is Enable",
                ["name"],
            )
            if self._config == "Inspur-NF5280M6":
                host, user, passwd = (
                    get_arg(f"{self._metric}_host"),
                    get_arg(f"{self._metric}_user"),
                    get_arg(f"{self._metric}_passwd"),
                )
                self._redfish_obj = redfish_client(
                    base_url=f"https://{host}", username=f"{user}", password=f"{passwd}"
                )

                self._redfish_obj.login(auth="session")

                # For Fan Num
                response = self._redfish_obj.get("/redfish/v1/Chassis/1/Thermal")
                res = response.dict
                self._fan_nums = len(res["Fans"])

                # For machine_info
                response = self._redfish_obj.get("/redfish/v1/Chassis/1")
                res = response.dict
                self._machine_info.info(
                    {"manufacturer": res["Manufacturer"], "model": res["Model"]}
                )

                def exit_func():
                    self._redfish_obj.logout()

                self._exit_func = exit_func
            else:
                logger.warning(
                    f"Specify non-support config {self._config}, disable BMC interface"
                )
                self._enabled = False
                return

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._exit_func()
        except AttributeError as e:
            logger.warning(f"Not set control/monitor methods way of shutdown")
        except Exception as e:
            logger.warning(f"Occur {e} when exit BMC component")
        logger.warning("BMC component exit")

    def get_attrs(self, argl):
        attrs = {}
        for arg in argl:
            if arg == "cauto" and self._config == "Inspur-NF5280M6":
                response = self._redfish_obj.get("/redfish/v1/Chassis/1/Thermal")
                res = response.dict
                if self._fan_nums > 0:
                    attrs["cauto"] = (
                        True
                        if res["Fans"][0]["Oem"]["Public"]["ControlMode"] == "Auto"
                        else False
                    )
                else:
                    logger.warning(f"No Fans")
            if arg == "fannums" and self._config == "Inspur-NF5280M6":
                attrs["fannums"] = self._fan_nums
            else:
                logger.warning(f"Unknown BMC get attr config: {arg}/{self._config}")
        return attrs

    def inspur_nf5280m6_control(self, argl):
        result = {}
        argl_iter = iter(argl)
        response = self._redfish_obj.get("/redfish/v1/Chassis/1/Thermal")
        etag = None
        for i in response.getheaders():
            if str(i[0]).lower() == "etag":
                etag = i[1]
        if etag is None:
            result["error"] = "Could not get If-Match"
            return result
        while True:
            try:
                arg = next(argl_iter)
            except:
                break
            if arg == "set-auto":
                response = self._redfish_obj.patch(
                    "/redfish/v1/Chassis/1/Thermal",
                    headers={"If-Match": etag, "Content-Type": "application/json"},
                    body={
                        "Oem": {
                            "Fans": {
                                "ControlMode": "Auto",
                            }
                        }
                    },
                )
            elif arg == "change-speed":
                try:
                    fans = next(argl_iter)
                    speed = next(argl_iter)
                except:
                    logger.warning("Not specify fans or speed")
                    result["error"] = "bmc control failed"
                    return result
                if fans == "all":
                    for i in range(self._fan_nums):
                        response = self._redfish_obj.patch(
                            "/redfish/v1/Chassis/1/Thermal",
                            headers={
                                "If-Match": etag,
                                "Content-Type": "application/json",
                            },
                            body={
                                "Oem": {
                                    "Fans": {
                                        "ControlMode": "Manual",
                                        "MemberId": i,
                                        "SpeedRatio": int(speed),
                                    }
                                }
                            },
                        )
                else:
                    fanlist = self.parse_fans(fans)
                    if fanlist is None:
                        logger.warning(f"parse error: {str(argl)} Check your syntax")
                        result["error"] = "bmc change fan speed syntax error"
                        return result
                    fanlist = list(set(fanlist))
                    for f in fanlist:
                        response = self._redfish_obj.patch(
                            "/redfish/v1/Chassis/1/Thermal",
                            headers={
                                "If-Match": etag,
                                "Content-Type": "application/json",
                            },
                            body={
                                "Oem": {
                                    "Fans": {
                                        "ControlMode": "Manual",
                                        "MemberId": f,
                                        "SpeedRatio": int(speed),
                                    }
                                }
                            },
                        )
            else:
                result["error"] = "Unknown BMC control config"
                return result
        result["success"] = "bmc control success"
        return result

    def parse_fans(self, gpus: str) -> list:
        """FAN/FAN0,FAN1,...FANx/FAN0-FANx/FAN0-FANx1/FANx2-FANx3

        Where all use index

        Args:
            gpus (str): _description_

        Returns:
            list: _description_
        """
        ret = []
        for i in gpus.split(","):
            if fans_list.match(i):
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

    def inspur_nf5280m6_update(self):
        final_output = bytes("", "utf-8")

        # for fan info
        response = self._redfish_obj.get("/redfish/v1/Chassis/1/Thermal")
        res = response.dict
        for f, fan in enumerate(res["Fans"]):
            name = fan["Name"]
            status = fan["Status"]
            state = status["State"]
            health = status["Health"]
            reading = fan["Reading"]
            readingunits = fan["ReadingUnits"]
            oem = fan["Oem"]
            oem_public = oem["Public"]
            controlmode = oem_public["ControlMode"]
            speedratio = oem_public["SpeedRatio"]
            self._fan_info.labels(index=str(f), name=name).info(
                {
                    "state": state,
                    "health": health,
                    "controlmode": controlmode,
                    "speedratio": str(speedratio),
                }
            )
            self._fan_read.labels(
                index=str(f), name=name, readingunits=readingunits
            ).set(reading)
        # for power and powersupply info
        response = self._redfish_obj.get("/redfish/v1/Chassis/1/Power")
        res = response.dict
        for pl, powersupply in enumerate(res["PowerSupplies"]):
            poutw = powersupply["PowerOutputWatts"]
            pinw = powersupply["PowerInputWatts"]
            self._powersupply_power.labels(index=pl, mode="input").set(pinw)
            self._powersupply_power.labels(index=pl, mode="output").set(poutw)
        oem = res["Oem"]
        oem_public = oem["Public"]
        cpupower = oem_public["CurrentCPUPowerWatts"]
        mempower = oem_public["CurrentMemoryPowerWatts"]
        fanpower = oem_public["CurrentFANPowerWatts"]
        totalpower = oem_public["TotalPower"]
        self._power_info.labels(component="cpu").set(cpupower)
        self._power_info.labels(component="mem").set(mempower)
        self._power_info.labels(component="fan").set(fanpower)
        self._power_info.labels(component="total").set(totalpower)

        # for sensors
        response = self._redfish_obj.get("/redfish/v1/Chassis/1/ThresholdSensors")
        res = response.dict
        for sensor in res["Sensors"]:
            name = sensor["Name"]
            status = sensor["Status"]
            unit = sensor["unit"]
            readingvalue = sensor["ReadingValue"]
            if readingvalue is None:
                readingvalue = "-1"
            else:
                readingvalue = str(readingvalue)
            self._threshold_sensors.labels(name=name, unit=unit).info(
                {"status": status}
            )
            self._threshold_sensors_values.labels(name=name, unit=unit).set(
                readingvalue
            )

        response = self._redfish_obj.get("/redfish/v1/Chassis/1/DiscreteSensors")
        res = response.dict
        for sensor in res["Sensors"]:
            name = sensor["Name"]
            status = sensor["Status"]
            self._discrete_sensors.labels(name=name).set(1 if status == "Enable" else 0)

        final_output += (
            generate_latest(self._machine_info)
            + generate_latest(self._fan_info)
            + generate_latest(self._fan_read)
            + generate_latest(self._power_info)
            + generate_latest(self._powersupply_power)
            + generate_latest(self._threshold_sensors)
            + generate_latest(self._threshold_sensors_values)
            + generate_latest(self._discrete_sensors)
        )
        return final_output

    @enabled
    @locked
    def update(self) -> bytes:
        final_output = bytes("", "utf-8")
        if self._config == "Inspur-NF5280M6":
            final_output += self.inspur_nf5280m6_update()
        return final_output

    @enabled
    @locked
    def control(self, argl):
        result = {}
        if self._config == "Inspur-NF5280M6":
            result = self.inspur_nf5280m6_control(argl)
        else:
            logger.warning("No Server config choose")
            result = {"error": "No Server config choose"}
        return result
