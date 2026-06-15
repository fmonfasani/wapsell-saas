"""Admin dashboard for real-time sales analytics.

Provides aggregated metrics and insights for tenant admins.

Structure:
  api.py - Dashboard API endpoints
"""

from __future__ import annotations

from wapsell.sales.dashboard.api import DashboardAPI

__all__ = [
    "DashboardAPI",
]
