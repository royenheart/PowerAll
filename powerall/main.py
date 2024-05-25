#!/bin/env python3

"""
Deploy on single node
"""

from opts.argsopt import *
from opts.logopt import *
from flask import Response, Flask, request, jsonify
from components.cpu import CPU
from components.nvgpu import NVGPU
from components.bmc import BMC
from prometheus_client import Info, generate_latest
import os
import socket

# Set basic args
add_option("-s", "--server", type=str, default="127.0.0.1", help="Specify server")
add_option("-p", "--port", type=int, default=8082, help="Specify metrics port")
add_option("--debug", type=bool, default=False, help="Enable Debug Mode")
add_option(
    "--cluster",
    type=str,
    default="powerall",
    help="Set controller/collector in which cluster",
)

app = Flask(__name__)

# Init components and execute __enter__ steps
with CPU() as cpu, NVGPU() as nvgpu, BMC() as bmc:
    # Init components
    components = {"cpu": cpu, "nvgpu": nvgpu, "bmc": bmc}

    # Parse args
    parse_args()

    # Set up logger
    host, port, debug = get_arg("server"), get_arg("port"), get_arg("debug")
    setup_logger(debug)

    # Set up uname info
    uname = os.uname()
    fqdn = socket.getfqdn()
    hostname = socket.gethostname()
    domainname = fqdn[len(hostname) + 1 :] if fqdn != hostname else ""
    uname_info = Info(
        f"powerall_uname_info",
        "Labeled system information as provided by the uname system call.",
    )
    uname_info.info(
        {
            "sysname": uname.sysname,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
            "nodename": uname.nodename,
            "domainname": domainname,
        }
    )

    const_output = generate_latest(uname_info)

    cpu.setup()
    nvgpu.setup()
    bmc.setup()

    @app.route("/metrics")
    def monitor():
        """Set Monitor Route

        Returns:
            _type_: _description_
        """
        output = const_output
        logger.warning(f"Start Update")
        for c in components.values():
            upds = c.update()
            if upds is not None and isinstance(upds, bytes):
                output += upds
            else:
                logger.warning(f"Component {c.name} didn't capture output of monitor")
        logger.warning(f"End Update")
        return Response(output, mimetype="text/plain")

    @app.route("/api/control/<component>")
    def control(component):
        """Set Controll Route

        Args:
            component (_type_): _description_

        Returns:
            _type_: _description_
        """
        values = list(request.args.values())
        result = {}

        try:
            result = components[component].control(values)
        except KeyError:
            logger.warning("Not support component")
            result["error"] = "Not support component"

        return jsonify(result)

    @app.route("/api/get/<component>")
    def attr(component):
        """Get Attr Route

        Args:
            component (_type_): _description_

        Returns:
            _type_: _description_
        """
        values = list(request.args.values())
        result = {}

        try:
            result = components[component].get_attrs(values)
        except KeyError as e:
            logger.warning("Not support component")
            result["error"] = "Not support component"

        return jsonify(result)

    @app.route("/api/components")
    def GetComponents():
        """Get Support Components

        Returns:
            _type_: _description_
        """
        lists = [x for x in components.keys()]
        return jsonify(lists)

    if __name__ == "__main__":
        logger.warning(f"Running on http://{host}:{port}")
        app.run(host, port, debug)
