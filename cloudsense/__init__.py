"""CloudSense - AWS Cost Dashboard

A minimal web interface for tracking AWS costs with customizable budget alerts and service breakdowns.
"""

__version__ = "0.1.0"
__author__ = "veloduff"

from .app import create_app

__all__ = ["create_app"]