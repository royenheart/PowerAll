"""
Wrapper for argparse
"""

from argparse import ArgumentParser
from .logopt import *

called_parse_args = False
parser = ArgumentParser(
    description="PowerAll",
)

def add_option(*args, **kwargs):
    """Add Option
    """
    if called_parse_args:
        logger.warning("Can't add an option after calling parser.parse_args")

    parser.add_argument(*args, **kwargs)

def parse_args():
    """Parse Args
    Once args are parsed, call get_arg next.
    """
    global called_parse_args
    called_parse_args = True
    global args
    args = parser.parse_args()

def get_arg(arg_name: str) -> any:
    return getattr(args, arg_name)

def print_help(*args, **kwargs):
    parser.print_help(*args, **kwargs)