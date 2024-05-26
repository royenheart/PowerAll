from opts.logopt import *
from opts.argsopt import *
from prometheus_client import Gauge, Info, generate_latest
from .component import Component
from typing import Dict, List
import threading
import re

secondsPerTick = 1.0 / 1000.0
# Read sectors and write sectors are the "standard UNIX 512-byte sectors, not any device- or filesystem-specific block size."
# See also https://www.kernel.org/doc/Documentation/block/stat.txt
unixSectorSize = 512.0
# Default ignore disk partition, for example exclude sda1, include sda
diskstatsDefaultIgnoredDevices = "^(z?ram|loop|fd|(h|s|v|xv)d[a-z]|nvme\\d+n\\d+p)\\d+$"
# Udev device properties.
# Device Property Prefix see https://github.com/systemd/systemd/blob/main/src/udev/udevadm-info.c
udevDevicePropertyPrefix = "E:"
udevDMLVLayer = "DM_LV_LAYER"
udevDMLVName = "DM_LV_NAME"
udevDMName = "DM_NAME"
udevDMUUID = "DM_UUID"
udevDMVGName = "DM_VG_NAME"
udevIDATA = "ID_ATA"
udevIDATARotationRateRPM = "ID_ATA_ROTATION_RATE_RPM"
udevIDATASATA = "ID_ATA_SATA"
udevIDATASATASignalRateGen1 = "ID_ATA_SATA_SIGNAL_RATE_GEN1"
udevIDATASATASignalRateGen2 = "ID_ATA_SATA_SIGNAL_RATE_GEN2"
udevIDATAWriteCache = "ID_ATA_WRITE_CACHE"
udevIDATAWriteCacheEnabled = "ID_ATA_WRITE_CACHE_ENABLED"
udevIDFSType = "ID_FS_TYPE"
udevIDFSUsage = "ID_FS_USAGE"
udevIDFSUUID = "ID_FS_UUID"
udevIDFSVersion = "ID_FS_VERSION"
udevIDModel = "ID_MODEL"
udevIDPath = "ID_PATH"
udevIDRevision = "ID_REVISION"
udevIDSerialShort = "ID_SERIAL_SHORT"
udevIDWWN = "ID_WWN"
udevSCSIIdentSerial = "SCSI_IDENT_SERIAL"
diskstatMajorNumber = 0
diskstatMinorNumber = 1
diskstatDeviceName = 2
diskstatReadIOs = 3
diskstatReadMerges = 4
diskstatReadSectors = 5
diskstatReadTicks = 6
diskstatWriteIOs = 7
diskstatWriteMerges = 8
diskstatWriteSectors = 9
diskstatWriteTicks = 10
diskstatIOsInProgress = 11
diskstatIOsTotalTicks = 12
diskstatWeightedIOTicks = 13
diskstatDiscardIOs = 14
diskstatDiscardMerges = 15
diskstatDiscardSectors = 16
diskstatDiscardTicks = 17
diskstatFlushRequestsCompleted = 18
diskstatTimeSpentFlushing = 19


class DISK(Component):
    def __init__(self) -> None:
        self._metric = "disk"

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
        self._diskstat = Gauge(
            f"{self._metric}_diskstat",
            "Disk stat in different metric",
            ["disk", "metric"],
        )

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def get_attrs(self, argl):
        pass

    @enabled
    @locked
    def update(self) -> bytes:
        output = bytes("", "utf-8")
        # use /proc/diskstats together with /run/udev/data to get disk info
        diskstats: Dict[str, List[int]] = {}
        udevstats: Dict[str, Dict[str, str]] = {}
        with open("/proc/diskstats", "r") as f:
            for disk in f.readlines():
                disk = [x for x in disk.strip().split(sep=" ") if x != ""]
                if (
                    re.match(diskstatsDefaultIgnoredDevices, disk[diskstatDeviceName])
                    is None
                ):
                    diskstats[disk[diskstatDeviceName]] = disk
        for disk in diskstats.values():
            devname = disk[diskstatDeviceName]
            major = disk[diskstatMajorNumber]
            minor = disk[diskstatMinorNumber]
            with open(f"/run/udev/data/b{major}:{minor}", "r") as udev:
                for p in udev.readlines():
                    if p.startswith(udevDevicePropertyPrefix):
                        porpers = p[2:].strip().split(sep="=", maxsplit=1)
                        if len(porpers) == 2:
                            if devname not in udevstats:
                                udevstats[devname] = {}
                            udevstats[devname][porpers[0]] = porpers[1]
        for disk in diskstats.values():
            devname = disk[diskstatDeviceName]
            try:
                self._diskstat.labels(disk=devname, metric="reads_completed_total").set(
                    disk[diskstatReadIOs]
                )
                self._diskstat.labels(disk=devname, metric="reads_merged_total").set(
                    disk[diskstatReadMerges]
                )
                self._diskstat.labels(disk=devname, metric="read_bytes_total").set(
                    float(disk[diskstatReadSectors]) * unixSectorSize
                )
                self._diskstat.labels(
                    disk=devname, metric="read_time_seconds_total"
                ).set(float(disk[diskstatReadTicks]) * secondsPerTick)
                self._diskstat.labels(
                    disk=devname, metric="writes_completed_total"
                ).set(disk[diskstatWriteIOs])
                self._diskstat.labels(disk=devname, metric="writes_merged_total").set(
                    disk[diskstatWriteMerges]
                )
                self._diskstat.labels(disk=devname, metric="written_bytes_total").set(
                    float(disk[diskstatWriteSectors]) * unixSectorSize
                )
                self._diskstat.labels(
                    disk=devname, metric="write_time_seconds_total"
                ).set(float(disk[diskstatWriteTicks]) * secondsPerTick)
                self._diskstat.labels(disk=devname, metric="io_now").set(
                    disk[diskstatIOsInProgress]
                )
                self._diskstat.labels(disk=devname, metric="io_time_seconds_total").set(
                    float(disk[diskstatIOsTotalTicks]) * secondsPerTick
                )
                self._diskstat.labels(
                    disk=devname, metric="io_time_weighted_seconds_total"
                ).set(float(disk[diskstatWeightedIOTicks]) * secondsPerTick)
                self._diskstat.labels(
                    disk=devname, metric="discards_completed_total"
                ).set(disk[diskstatDiscardIOs])
                self._diskstat.labels(disk=devname, metric="discards_merged_total").set(
                    disk[diskstatDiscardMerges]
                )
                self._diskstat.labels(
                    disk=devname, metric="discarded_sectors_total"
                ).set(disk[diskstatDiscardSectors])
                self._diskstat.labels(
                    disk=devname, metric="discard_time_seconds_total"
                ).set(float(disk[diskstatDiscardTicks]) * secondsPerTick)
                self._diskstat.labels(disk=devname, metric="flush_requests_total").set(
                    disk[diskstatFlushRequestsCompleted]
                )
                self._diskstat.labels(
                    disk=devname, metric="flush_requests_time_seconds_total"
                ).set(float(disk[diskstatTimeSpentFlushing]) * secondsPerTick)
            except IndexError:
                continue
        output += generate_latest(self._diskstat)
        return output

    @enabled
    @locked
    def control(self, argl):
        raise NotImplementedError("Control for disk not implemented")
