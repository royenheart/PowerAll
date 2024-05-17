"""
Wrapper for log    
"""

import logging

logger = logging.getLogger()

def setup_logger(debug: bool):
    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(levelname)s - %(name)s: %(message)s'
        )
    else:
        logging.basicConfig(
            level=logging.WARNING,
            format='%(asctime)s %(levelname)s - %(name)s: %(message)s'
        )