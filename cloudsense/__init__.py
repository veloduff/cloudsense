"""CloudSense - AWS Cost Dashboard

A CLI and interactive GUI for AWS cost tracking.
"""

__version__ = "0.1.9"
__author__ = "veloduff"

from .app import create_app

__all__ = ["create_app"]