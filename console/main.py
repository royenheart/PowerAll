from dash import Dash, html, dcc, Input, Output, State, ALL, MATCH, Patch, no_update
from argparse import ArgumentParser
import requests
import json
import yaml
import logging
import os
import sys

grafana_url = "http://127.0.0.1:3000/d/f34247bf-b37b-4e33-918a-7cbf80feae5f/power-dashboard?orgId=1"
curr_path = os.curdir

parser = ArgumentParser(
    description="PowerAll-Frontend",
)
parser.add_argument(
    "-s", "--server", type=str, default="127.0.0.1", help="Specify server"
)
parser.add_argument("-p", "--port", type=int, default=8085, help="Specify port")
parser.add_argument(
    "-cp",
    "--config-path",
    type=str,
    default=curr_path,
    help="Specify config path",
)
args = parser.parse_args()
logger = logging.getLogger()
debug = os.environ.get("DEBUG")
if debug:
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)s - %(name)s: %(message)s"
    )
else:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s - %(name)s: %(message)s",
    )

# Parse config file
cf = os.path.join(args.config_path, "prometheus.yml")
try:
    with open(cf, "r") as f:
        configs = yaml.safe_load(f)
except FileNotFoundError as e:
    logger.error(f"Config file: {cf} not found")
    sys.exit(1)

host, port = args.server, args.port


class cluster:
    stored_cs = {}

    def __init__(self, name) -> None:
        self._name = name
        self._jobs = {}

    @staticmethod
    def cs(name):
        if name in cluster.stored_cs:
            return cluster.stored_cs[name]
        else:
            c = cluster(name=name)
            cluster.stored_cs[name] = c
            return c

    def fannums(self, job):
        if job in self._jobs and "fannums" in self._jobs[job]:
            return self._jobs[job]["fannums"]
        else:
            return self._fannums

    def set_fannums(self, job, fannums):
        self._jobs[job] = {}
        self._jobs[job]["fannums"] = fannums

    @property
    def name(self):
        return self._name

    def set_name(self, name):
        self._name = name


app = Dash(__name__)

contents = []

# Set embeded Grafana
gu_iframe = html.Div(
    style={"width": "48%", "display": "inline-block"},
    children=[
        html.H2(children="Monitor", style={"textAlign": "center"}),
        html.Iframe(
            id="gu_iframe",
            src="",
            width="100%",
            height="800px",
            style=dict(border="1px solid black"),
            name="gu-embeded",
            title="Grafana Embeded",
        ),
    ],
)

# Set Choosen Cluster
clusters = {}
for job in configs["scrape_configs"]:
    job_name = job["job_name"]
    if job_name != "prometheus":
        for target in job["static_configs"]:
            t = target["targets"][0]
            cluster_name = target["labels"]["cluster"]
            if cluster_name not in clusters:
                clusters[cluster_name] = {"name": cluster_name, "jobs": []}
            clusters[cluster_name]["jobs"].append(
                {"job_name": job_name, "hosts": {target["labels"]["exporter"]: t}}
            )
clusters = list(clusters.values())
if clusters is None or len(clusters) == 0:
    logger.error("No cluster config")
    sys.exit(1)
choosen_cluster = dcc.Dropdown(
    id="choosen_cluster",
    options=[x["name"] for x in clusters],
    value=None if len(clusters) == 0 else clusters[0]["name"],
    clearable=False,
    multi=False,
)


@app.callback(
    Output("control-div", "children"),
    Output("gu_iframe", "src"),
    Input("choosen_cluster", "value"),
)
def chose_cluster(c):
    control_panels = []
    for cs in clusters:
        if cs["name"] == c:
            chosens = cs
            break
    # Set powerall
    poweralls = []
    for job in chosens["jobs"]:
        if "powerall" in job["hosts"]:
            poweralls.append(job["hosts"]["powerall"])
    jobs = []
    # Create Cluster
    me = cluster.cs(c)
    for job in poweralls:
        coms = []
        # Add CPU Component
        cpuc_childs = []
        try:
            res = requests.get(f"http://{job}/api/get/cpu?a=cpufreqs")
            res_text = res.text.strip()
            attrs = json.loads(res_text)
            cpufreqs = attrs["cpufreqs"]
            cpunums = cpufreqs["cpunums"]
            scaling_available_governors = cpufreqs["ava_governors"]
            scaling_available_frequencies = cpufreqs["ava_freqs"]
            disable_gov_change = False if len(scaling_available_governors) > 0 else True
            cpuc_childs.append(
                html.H5(
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "cpu",
                        "func": "gov-all",
                    }
                )
            )
            cpuc_childs.append(
                dcc.Dropdown(
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "cpu",
                        "func": "change-gov-all",
                    },
                    options=[x for x in scaling_available_governors],
                    value=None,
                    clearable=False,
                    multi=False,
                    disabled=disable_gov_change,
                )
            )
            cpuc_childs.append(
                html.H5(
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "cpu",
                        "func": "freq-all",
                    }
                )
            )
            cpuc_childs.append(
                dcc.Dropdown(
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "cpu",
                        "func": "change-freq-all",
                    },
                    options=[x for x in scaling_available_frequencies],
                    value=None,
                    clearable=False,
                    multi=False,
                    disabled=True,
                )
            )
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"get {job} cpufreq info failed, skip create CPU component")
        cpuc = html.Div(
            id={"cluster": c, "job": job, "com": "cpu"}, children=cpuc_childs
        )
        coms.extend([html.H4(children=f"Component CPU"), cpuc])
        # Add NVGPU Component
        nvgpuc_childs = []
        try:
            res = requests.get(f"http://{job}/api/get/nvgpu?a=plc")
            res_text = res.text.strip()
            attrs = json.loads(res_text)
            plc = attrs["plc"]
            # logger.warning(f"{plc}")
            for i, rangs in enumerate(plc):
                min = rangs[0] / 1000
                max = rangs[1] / 1000
                nvgpuc_childs.append(html.H5(children=f"GPU {i}"))
                nvgpuc_childs.append(
                    dcc.Slider(
                        id={
                            "cluster": c,
                            "job": job,
                            "com": "nvgpu",
                            "func": "change-pl",
                            "index": 0,
                            "gpuindex": i,
                        },
                        min=min,
                        max=max,
                        step=10,
                        updatemode="mouseup",
                    )
                )
                nvgpuc_childs.append(
                    html.H5(
                        id={
                            "cluster": c,
                            "job": job,
                            "com": "nvgpu",
                            "func": "pl",
                            "index": 0,
                            "gpuindex": i,
                        }
                    )
                )
        except requests.exceptions.ConnectionError as e:
            logger.warning(
                f"get {job} power limits failed, skip create NVGPU component"
            )
        nvgpuc = html.Div(
            id={"cluster": c, "job": job, "com": "nvgpu"}, children=nvgpuc_childs
        )
        coms.extend([html.H4(children=f"Component NVGPU"), nvgpuc])
        # Add BMC Component
        bmc_childs = []
        try:
            res = requests.get(f"http://{job}/api/get/bmc?a=fannums")
            res_text = res.text.strip()
            attrs = json.loads(res_text)
            fannums = attrs["fannums"]
            me.set_fannums(fannums=fannums, job=job)
            bmc_childs.append(
                html.Button(
                    "FanAuto",
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "bmc",
                        "func": "set-auto-all",
                    },
                )
            )
            bmc_childs.append(
                html.H5(
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "bmc",
                        "func": "auto-all",
                    }
                )
            )
            bmc_childs.append(
                dcc.Slider(
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "bmc",
                        "func": "change-speed-all",
                    },
                    min=0,
                    max=100,
                    step=5,
                    updatemode="mouseup",
                )
            )
            bmc_childs.append(
                html.H5(
                    id={
                        "cluster": c,
                        "job": job,
                        "com": "bmc",
                        "func": "speed-all",
                    }
                )
            )
            for f in range(fannums):
                bmc_childs.append(
                    dcc.Slider(
                        id={
                            "cluster": c,
                            "job": job,
                            "com": "bmc",
                            "func": "change-speed",
                            "index": f,
                        },
                        min=0,
                        max=100,
                        step=5,
                        updatemode="mouseup",
                    )
                )
                bmc_childs.append(
                    html.H5(
                        id={
                            "cluster": c,
                            "job": job,
                            "com": "bmc",
                            "func": "speed",
                            "index": f,
                        }
                    )
                )
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"get {job} fannums failed, skip create BMC component")
        bmcc = html.Div(
            id={"cluster": c, "job": job, "com": "bmc"}, children=bmc_childs
        )
        coms.extend([html.H4(children=f"Component BMC"), bmcc])
        # Add Job
        jobs.extend(
            [
                html.H3(children=f"Job {job}"),
                html.Div(id={"cluster": c, "job": job}, children=coms),
            ]
        )
    # Add total Component

    # Add Cluster
    cls = html.Div(
        id={"cluster": c},
        children=jobs,
    )
    control_panels.append(html.H2(children=f"Control", style={"textAlign": "center"}))
    control_panels.append(cls)
    # Set Grafana
    return control_panels, grafana_url + f"&var-cluster={c}"


@app.callback(
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "cpu",
            "func": "gov-all",
        },
        "children",
    ),
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "cpu",
            "func": "change-freq-all",
        },
        "disabled",
    ),
    Input(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "cpu",
            "func": "change-gov-all",
        },
        "value",
    ),
    State(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "cpu",
            "func": "change-gov-all",
        },
        "id",
    ),
    prevent_initial_call=True,
)
def change_gov(value, id):
    job = id["job"]
    try:
        res = requests.get(f"http://{job}/api/control/cpu?a=change-gov&b=all&c={value}")
        res_text = res.text.strip()
        status = json.loads(res_text)
        if len(status) != 0 and not "error" in status and "success" in status:
            logger.warning(f"{job} sent set cpufreq gov success")
            enable_change_freq = value == "userspace"
            return f"Change GOV {value}", not enable_change_freq
        else:
            logger.warning(
                f"{job} sent set cpufreq gov failed due to {status['error']}"
            )
            return "Failed", True
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"{job} sent set cpufreq gov failed due to {e}")
        return "Failed", True


@app.callback(
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "cpu",
            "func": "freq-all",
        },
        "children",
    ),
    Input(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "cpu",
            "func": "change-freq-all",
        },
        "value",
    ),
    State(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "cpu",
            "func": "change-freq-all",
        },
        "id",
    ),
    prevent_initial_call=True,
)
def change_freq(value, id):
    job = id["job"]
    try:
        res = requests.get(
            f"http://{job}/api/control/cpu?a=change-freq&b=all&c={value}"
        )
        res_text = res.text.strip()
        status = json.loads(res_text)
        if len(status) != 0 and not "error" in status and "success" in status:
            logger.warning(f"{job} sent set cpu freq success")
            return f"Change Freq {value}"
        else:
            logger.warning(f"{job} sent set cpu freq failed due to {status['error']}")
            return "Failed"
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"{job} sent set cpu freq failed due to {e}")
        return "Failed"


@app.callback(
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "auto-all",
        },
        "children",
    ),
    Input(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "set-auto-all",
        },
        "n_clicks",
    ),
    State(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "set-auto-all",
        },
        "id",
    ),
    prevent_initial_call=True,
)
def set_auto(n_clicks, id):
    job = id["job"]
    try:
        res = requests.get(f"http://{job}/api/control/bmc?a=set-auto")
        res_text = res.text.strip()
        status = json.loads(res_text)
        if len(status) != 0 and not "error" in status and "success" in status:
            logger.warning(f"{job} sent set fan auto control success")
            return "Auto Control!"
        else:
            logger.warning(f"{job} sent set fan auto failed due to {status['error']}")
            return "Failed"
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"{job} sent change fan auto failed due to {e}")
        return "Failed"


@app.callback(
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "speed",
            "index": MATCH,
        },
        "children",
    ),
    Input(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "change-speed",
            "index": MATCH,
        },
        "value",
    ),
    State(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "change-speed",
            "index": MATCH,
        },
        "id",
    ),
    prevent_initial_call=True,
)
def change_speed(value, id):
    job = id["job"]
    index = id["index"]
    try:
        res = requests.get(
            f"http://{job}/api/control/bmc?a=change-speed&b={index}&c={value}"
        )
        res_text = res.text.strip()
        status = json.loads(res_text)
        if len(status) != 0 and not "error" in status and "success" in status:
            logger.warning(f"{job} sent change fan {index} speed to {value} success")
            return value
        else:
            logger.warning(
                f"{job} sent change fan {index} speed failed due to {status['error']}"
            )
            return "Change failed"
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"{job} sent change fan {index} speed failed due to {e}")
        return "Change failed"


@app.callback(
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "speed-all",
        },
        "children",
    ),
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "change-speed",
            "index": ALL,
        },
        "value",
    ),
    Input(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "change-speed-all",
        },
        "value",
    ),
    State(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "bmc",
            "func": "change-speed-all",
        },
        "id",
    ),
    prevent_initial_call=True,
)
def change_speed_all(value, id):
    cs = id["cluster"]
    job = id["job"]
    me = cluster.cs(cs)
    fannums = me.fannums(job=job)

    return "change-all", [value] * fannums


@app.callback(
    Output(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "nvgpu",
            "func": "pl",
            "index": MATCH,
            "gpuindex": MATCH,
        },
        "children",
    ),
    Input(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "nvgpu",
            "func": "change-pl",
            "index": MATCH,
            "gpuindex": MATCH,
        },
        "value",
    ),
    State(
        {
            "cluster": MATCH,
            "job": MATCH,
            "com": "nvgpu",
            "func": "change-pl",
            "index": MATCH,
            "gpuindex": MATCH,
        },
        "id",
    ),
    prevent_initial_call=True,
)
def change_pl(value, id):
    cs = id["cluster"]
    job = id["job"]
    gpuindex = id["gpuindex"]
    try:
        res = requests.get(
            f"http://{job}/api/control/nvgpu?a=change-pl&b={gpuindex}&c={value}"
        )
        res_text = res.text.strip()
        status = json.loads(res_text)
        if len(status) != 0 and not "error" in status and "success" in status:
            logger.warning(f"{job} sent change nvgpu pl to {value} success")
            return value
        else:
            logger.warning(
                f"{job} sent change nvgpu pl failed due to {status['error']}"
            )
            return "Change failed"
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"{job} sent change nvgpu pl failed due to {e}")
        return "Change failed"


contents.append(html.H1(children="PowerAll Frontend", style={"textAlign": "center"}))
contents.append(html.H2(children="Select Cluster", style={"textAlign": "center"}))
contents.append(choosen_cluster)
contents.append(
    html.Div(
        id="monitor-controls",
        style={
            "display": "flex",
            "flex-direction": "row",
            "flex-wrap": "nowarp",
            "justify-content": "space-between",
            "align-items": "flex-start",
        },
        children=[
            gu_iframe,
            html.Div(
                id="control-div",
                children=[],
                style={"width": "48%", "display": "inline-block"},
            ),
        ],
    )
)

app.layout = html.Div(contents)

if __name__ == "__main__":
    logger.warning(f"Running on http://{host}:{port}")
    app.run(host, port, debug)
