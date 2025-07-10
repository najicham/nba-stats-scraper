# shared/utils/metrics_utils.py
"""
Custom metrics utilities for NBA platform
"""

import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from google.cloud import monitoring_v3

logger = logging.getLogger(__name__)


class MetricsClient:
    """Custom metrics client for NBA platform"""
    
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.client = monitoring_v3.MetricServiceClient()
        self.project_name = f"projects/{project_id}"
    
    def send_metric(self, metric_name: str, value: float, 
                   labels: Optional[Dict[str, str]] = None,
                   metric_type: str = "GAUGE") -> bool:
        """
        Send custom metric to Cloud Monitoring
        
        Args:
            metric_name: Name of the metric (will be prefixed with custom.googleapis.com/nba/)
            value: Metric value
            labels: Optional labels for the metric
            metric_type: GAUGE, COUNTER, or CUMULATIVE
            
        Returns:
            True if successful
        """
        if labels is None:
            labels = {}
        
        full_metric_name = f"custom.googleapis.com/nba/{metric_name}"
        
        try:
            # Create the time series
            series = monitoring_v3.TimeSeries()
            series.metric.type = full_metric_name
            series.metric.labels.update(labels)
            
            # Set resource labels
            series.resource.type = 'global'
            series.resource.labels['project_id'] = self.project_id
            
            # Create data point
            point = monitoring_v3.Point()
            point.interval.end_time.seconds = int(time.time())
            
            if metric_type == "GAUGE":
                point.value.double_value = float(value)
            else:
                point.value.int64_value = int(value)
            
            series.points = [point]
            
            # Send to Cloud Monitoring
            self.client.create_time_series(
                name=self.project_name, 
                time_series=[series]
            )
            
            logger.debug(f"Sent metric {metric_name}={value} with labels {labels}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send metric {metric_name}: {e}")
            return False
    
    def create_metric_descriptor(self, metric_name: str, description: str,
                               metric_kind: str = "GAUGE", 
                               value_type: str = "DOUBLE") -> bool:
        """
        Create a custom metric descriptor
        
        Args:
            metric_name: Name of the metric
            description: Human-readable description
            metric_kind: GAUGE, CUMULATIVE, or DELTA
            value_type: DOUBLE, INT64, BOOL, STRING
            
        Returns:
            True if successful
        """
        full_metric_name = f"custom.googleapis.com/nba/{metric_name}"
        
        descriptor = monitoring_v3.MetricDescriptor()
        descriptor.type = full_metric_name
        descriptor.description = description
        
        # Set metric kind
        if metric_kind == "GAUGE":
            descriptor.metric_kind = monitoring_v3.MetricDescriptor.MetricKind.GAUGE
        elif metric_kind == "CUMULATIVE":
            descriptor.metric_kind = monitoring_v3.MetricDescriptor.MetricKind.CUMULATIVE
        else:
            descriptor.metric_kind = monitoring_v3.MetricDescriptor.MetricKind.DELTA
        
        # Set value type
        if value_type == "DOUBLE":
            descriptor.value_type = monitoring_v3.MetricDescriptor.ValueType.DOUBLE
        elif value_type == "INT64":
            descriptor.value_type = monitoring_v3.MetricDescriptor.ValueType.INT64
        elif value_type == "BOOL":
            descriptor.value_type = monitoring_v3.MetricDescriptor.ValueType.BOOL
        else:
            descriptor.value_type = monitoring_v3.MetricDescriptor.ValueType.STRING
        
        try:
            self.client.create_metric_descriptor(
                name=self.project_name, 
                metric_descriptor=descriptor
            )
            logger.info(f"Created metric descriptor: {metric_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create metric descriptor {metric_name}: {e}")
            return False


# Global metrics client instance
_metrics_client = None


def get_metrics_client(project_id: Optional[str] = None) -> Optional[MetricsClient]:
    """Get or create global metrics client"""
    global _metrics_client
    
    if _metrics_client is None and project_id:
        _metrics_client = MetricsClient(project_id)
    
    return _metrics_client


def send_metric(metric_name: str, value: float, 
               labels: Optional[Dict[str, str]] = None,
               project_id: Optional[str] = None) -> bool:
    """
    Convenience function to send a metric
    
    Args:
        metric_name: Name of the metric
        value: Metric value
        labels: Optional labels
        project_id: Optional project ID (uses global client if not provided)
        
    Returns:
        True if successful
    """
    client = get_metrics_client(project_id)
    if client is None:
        logger.warning("No metrics client available")
        return False
    
    return client.send_metric(metric_name, value, labels)


def create_custom_metric(metric_name: str, description: str,
                        project_id: Optional[str] = None) -> bool:
    """
    Convenience function to create a custom metric descriptor
    
    Args:
        metric_name: Name of the metric
        description: Description of the metric
        project_id: Optional project ID
        
    Returns:
        True if successful
    """
    client = get_metrics_client(project_id)
    if client is None:
        logger.warning("No metrics client available")
        return False
    
    return client.create_metric_descriptor(metric_name, description)


# Standard NBA platform metrics
def send_scraper_metrics(scraper_name: str, records_count: int, 
                        execution_time: float, success: bool = True):
    """Send standard scraper metrics"""
    labels = {
        'scraper': scraper_name,
        'status': 'success' if success else 'failure'
    }
    
    send_metric('scraper_records_scraped', records_count, labels)
    send_metric('scraper_execution_time_seconds', execution_time, labels)
    send_metric('scraper_runs_total', 1, labels)


def send_processor_metrics(processor_name: str, records_processed: int,
                          processing_time: float, success: bool = True):
    """Send standard processor metrics"""
    labels = {
        'processor': processor_name,
        'status': 'success' if success else 'failure'
    }
    
    send_metric('processor_records_processed', records_processed, labels)
    send_metric('processor_execution_time_seconds', processing_time, labels)
    send_metric('processor_runs_total', 1, labels)


def send_report_metrics(report_type: str, reports_generated: int,
                       generation_time: float, success: bool = True):
    """Send standard report generation metrics"""
    labels = {
        'report_type': report_type,
        'status': 'success' if success else 'failure'
    }
    
    send_metric('reports_generated', reports_generated, labels)
    send_metric('report_generation_time_seconds', generation_time, labels)
    send_metric('report_runs_total', 1, labels)
