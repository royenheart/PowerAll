from setuptools import setup, find_packages

required_package = ["flask", "prometheus_client", "psutil", "pynvml", "redfish"]


setup(
    name="powerall",
    version="0.0.1",
    install_requires=required_package,
    packages=find_packages(exclude=["tests", "console"]),
    author="RoyenHeart",
    author_email="royenheart@outlook.com",
    description="PowerAll Cluster Power Monitor and Control",
    license="AGPL v3",
    entry_points={"console_scripts": ["powerall=powerall.main"]},
)
