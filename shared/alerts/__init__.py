"""
Shared alert management with rate limiting.
"""

from .alert_manager import AlertManager, get_alert_manager

__all__ = ['AlertManager', 'get_alert_manager']
