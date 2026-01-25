"""
Prometheus-compatible metrics for NBA Stats Scraper services.

Provides metrics in Prometheus exposition format for monitoring:
- Request counters (total requests, by endpoint, by status)
- Latency histograms (request duration distribution)
- Error rate gauges (current error percentage)
- Resource usage metrics (active connections, memory, etc.)

Usage:
    from shared.utils.prometheus_metrics import PrometheusMetrics, create_metrics_blueprint

    # Initialize metrics
    metrics = PrometheusMetrics(service_name='admin-dashboard')

    # Record requests
    metrics.record_request('/api/status', 'GET', 200, 0.045)

    # Get metrics in Prometheus format
    output = metrics.get_prometheus_output()

    # Or use the Flask blueprint
    app.register_blueprint(create_metrics_blueprint(metrics))

Created: 2026-01-23
"""

import time
import threading
import logging
import os
import psutil
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
from flask import Blueprint, Response

logger = logging.getLogger(__name__)


@dataclass
class HistogramBucket:
    """A histogram bucket for latency distribution."""
    le: float  # Less than or equal to (upper bound)
    count: int = 0


@dataclass
class MetricLabels:
    """Labels for a metric."""
    labels: Dict[str, str] = field(default_factory=dict)

    def to_prometheus_string(self) -> str:
        """Convert labels to Prometheus format: {key1="value1",key2="value2"}"""
        if not self.labels:
            return ''
        parts = [f'{k}="{v}"' for k, v in sorted(self.labels.items())]
        return '{' + ','.join(parts) + '}'


class Counter:
    """A Prometheus-style counter metric (monotonically increasing)."""

    def __init__(self, name: str, help_text: str, label_names: List[str] = None):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, amount: float = 1, labels: Dict[str, str] = None):
        """Increment the counter."""
        labels = labels or {}
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] += amount

    def get_samples(self) -> List[tuple]:
        """Get all samples as (labels_dict, value) tuples."""
        with self._lock:
            return [(dict(k), v) for k, v in self._values.items()]


class Gauge:
    """A Prometheus-style gauge metric (can go up or down)."""

    def __init__(self, name: str, help_text: str, label_names: List[str] = None):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self._values: Dict[tuple, float] = defaultdict(float)
        self._lock = threading.Lock()

    def set(self, value: float, labels: Dict[str, str] = None):
        """Set the gauge value."""
        labels = labels or {}
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1, labels: Dict[str, str] = None):
        """Increment the gauge."""
        labels = labels or {}
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] += amount

    def dec(self, amount: float = 1, labels: Dict[str, str] = None):
        """Decrement the gauge."""
        self.inc(-amount, labels)

    def get_samples(self) -> List[tuple]:
        """Get all samples as (labels_dict, value) tuples."""
        with self._lock:
            return [(dict(k), v) for k, v in self._values.items()]


class Histogram:
    """
    A Prometheus-style histogram metric for latency distribution.

    Default buckets are optimized for HTTP request latencies in seconds.
    """

    # Default buckets in seconds (5ms to 10s)
    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0]

    def __init__(self, name: str, help_text: str, label_names: List[str] = None, buckets: List[float] = None):
        self.name = name
        self.help_text = help_text
        self.label_names = label_names or []
        self.buckets = sorted(buckets or self.DEFAULT_BUCKETS)

        # Storage: key -> {bucket_counts: [...], sum: float, count: int}
        self._data: Dict[tuple, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _get_or_create_entry(self, key: tuple) -> Dict[str, Any]:
        """Get or create a histogram entry for the given label key."""
        if key not in self._data:
            self._data[key] = {
                'bucket_counts': [0] * len(self.buckets),
                'sum': 0.0,
                'count': 0
            }
        return self._data[key]

    def observe(self, value: float, labels: Dict[str, str] = None):
        """Observe a value (record it in the histogram)."""
        labels = labels or {}
        key = tuple(sorted(labels.items()))

        with self._lock:
            entry = self._get_or_create_entry(key)
            entry['sum'] += value
            entry['count'] += 1

            # Update the appropriate bucket count (non-cumulative storage)
            # Find the first bucket where value <= bucket_bound
            for i, bucket_bound in enumerate(self.buckets):
                if value <= bucket_bound:
                    entry['bucket_counts'][i] += 1
                    break  # Only count in one bucket

    def get_samples(self) -> List[tuple]:
        """
        Get all samples for Prometheus output.

        Returns list of (labels_dict, metric_suffix, value) tuples.
        Metric suffixes are: _bucket, _sum, _count
        """
        samples = []

        with self._lock:
            for key, entry in self._data.items():
                labels = dict(key)

                # Bucket samples (cumulative)
                cumulative_count = 0
                for i, bucket_bound in enumerate(self.buckets):
                    cumulative_count += entry['bucket_counts'][i]
                    bucket_labels = {**labels, 'le': str(bucket_bound)}
                    samples.append((bucket_labels, '_bucket', cumulative_count))

                # +Inf bucket (total count)
                samples.append(({**labels, 'le': '+Inf'}, '_bucket', entry['count']))

                # Sum and count
                samples.append((labels, '_sum', entry['sum']))
                samples.append((labels, '_count', entry['count']))

        return samples


class PrometheusMetrics:
    """
    Prometheus-compatible metrics collector for NBA Stats Scraper services.

    Provides standard metrics:
    - http_requests_total: Counter of total HTTP requests
    - http_request_duration_seconds: Histogram of request latencies
    - http_requests_in_flight: Gauge of currently processing requests
    - error_rate: Gauge of current error rate percentage
    - process_cpu_seconds_total: Counter of CPU time used
    - process_memory_bytes: Gauge of memory usage
    - service_info: Gauge with service metadata
    """

    def __init__(self, service_name: str, version: str = '1.0.0'):
        self.service_name = service_name
        self.version = version
        self.start_time = time.time()

        # Standard HTTP metrics
        self.http_requests_total = Counter(
            'http_requests_total',
            'Total number of HTTP requests',
            ['method', 'endpoint', 'status']
        )

        self.http_request_duration_seconds = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['method', 'endpoint']
        )

        self.http_requests_in_flight = Gauge(
            'http_requests_in_flight',
            'Number of HTTP requests currently being processed',
            ['method']
        )

        # Error tracking
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._total_counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

        self.error_rate = Gauge(
            'error_rate_percent',
            'Current error rate percentage',
            ['endpoint']
        )

        # Resource metrics
        self.process_cpu_seconds = Counter(
            'process_cpu_seconds_total',
            'Total user and system CPU time spent in seconds'
        )

        self.process_memory_bytes = Gauge(
            'process_memory_bytes',
            'Current process memory usage in bytes',
            ['type']
        )

        self.process_start_time = Gauge(
            'process_start_time_seconds',
            'Start time of the process since unix epoch in seconds'
        )

        # Service info (always 1, used for labels)
        self.service_info = Gauge(
            'service_info',
            'Service metadata',
            ['service', 'version']
        )

        # Custom application metrics
        self.custom_counters: Dict[str, Counter] = {}
        self.custom_gauges: Dict[str, Gauge] = {}
        self.custom_histograms: Dict[str, Histogram] = {}

        # Initialize service info
        self.service_info.set(1, {'service': service_name, 'version': version})
        self.process_start_time.set(self.start_time)

    def record_request(self, endpoint: str, method: str, status_code: int, duration_seconds: float):
        """
        Record an HTTP request.

        Args:
            endpoint: The request endpoint (e.g., '/api/status')
            method: HTTP method (GET, POST, etc.)
            status_code: HTTP response status code
            duration_seconds: Request duration in seconds
        """
        labels = {'method': method, 'endpoint': endpoint, 'status': str(status_code)}

        # Increment request counter
        self.http_requests_total.inc(labels=labels)

        # Record latency
        latency_labels = {'method': method, 'endpoint': endpoint}
        self.http_request_duration_seconds.observe(duration_seconds, labels=latency_labels)

        # Update error rate tracking
        with self._lock:
            self._total_counts[endpoint] += 1
            if status_code >= 400:
                self._error_counts[endpoint] += 1

            # Calculate error rate
            total = self._total_counts[endpoint]
            errors = self._error_counts[endpoint]
            if total > 0:
                error_rate = (errors / total) * 100
                self.error_rate.set(error_rate, {'endpoint': endpoint})

    def request_in_flight_inc(self, method: str = 'ALL'):
        """Increment in-flight request counter."""
        self.http_requests_in_flight.inc(labels={'method': method})

    def request_in_flight_dec(self, method: str = 'ALL'):
        """Decrement in-flight request counter."""
        self.http_requests_in_flight.dec(labels={'method': method})

    def update_resource_metrics(self):
        """Update process resource metrics."""
        try:
            process = psutil.Process()

            # Memory metrics
            memory_info = process.memory_info()
            self.process_memory_bytes.set(memory_info.rss, {'type': 'rss'})
            self.process_memory_bytes.set(memory_info.vms, {'type': 'vms'})

            # CPU metrics
            cpu_times = process.cpu_times()
            self.process_cpu_seconds.inc(cpu_times.user + cpu_times.system)

        except Exception as e:
            logger.debug(f"Failed to update resource metrics: {e}")

    def register_counter(self, name: str, help_text: str, label_names: List[str] = None) -> Counter:
        """Register a custom counter metric."""
        counter = Counter(name, help_text, label_names)
        self.custom_counters[name] = counter
        return counter

    def register_gauge(self, name: str, help_text: str, label_names: List[str] = None) -> Gauge:
        """Register a custom gauge metric."""
        gauge = Gauge(name, help_text, label_names)
        self.custom_gauges[name] = gauge
        return gauge

    def register_histogram(self, name: str, help_text: str, label_names: List[str] = None,
                          buckets: List[float] = None) -> Histogram:
        """Register a custom histogram metric."""
        histogram = Histogram(name, help_text, label_names, buckets)
        self.custom_histograms[name] = histogram
        return histogram

    def _format_metric_line(self, name: str, labels: Dict[str, str], value: float, suffix: str = '') -> str:
        """Format a single metric line in Prometheus format."""
        labels_str = MetricLabels(labels).to_prometheus_string()
        return f"{name}{suffix}{labels_str} {value}"

    def _format_counter(self, counter: Counter) -> str:
        """Format a counter metric for Prometheus output."""
        lines = [
            f"# HELP {counter.name} {counter.help_text}",
            f"# TYPE {counter.name} counter"
        ]
        for labels, value in counter.get_samples():
            lines.append(self._format_metric_line(counter.name, labels, value))
        return '\n'.join(lines)

    def _format_gauge(self, gauge: Gauge) -> str:
        """Format a gauge metric for Prometheus output."""
        lines = [
            f"# HELP {gauge.name} {gauge.help_text}",
            f"# TYPE {gauge.name} gauge"
        ]
        for labels, value in gauge.get_samples():
            lines.append(self._format_metric_line(gauge.name, labels, value))
        return '\n'.join(lines)

    def _format_histogram(self, histogram: Histogram) -> str:
        """Format a histogram metric for Prometheus output."""
        lines = [
            f"# HELP {histogram.name} {histogram.help_text}",
            f"# TYPE {histogram.name} histogram"
        ]
        for labels, suffix, value in histogram.get_samples():
            lines.append(self._format_metric_line(histogram.name, labels, value, suffix))
        return '\n'.join(lines)

    def get_prometheus_output(self) -> str:
        """
        Generate metrics in Prometheus exposition format.

        Returns:
            String in Prometheus text format
        """
        # Update resource metrics before output
        self.update_resource_metrics()

        sections = []

        # Standard HTTP metrics
        sections.append(self._format_counter(self.http_requests_total))
        sections.append(self._format_histogram(self.http_request_duration_seconds))
        sections.append(self._format_gauge(self.http_requests_in_flight))
        sections.append(self._format_gauge(self.error_rate))

        # Resource metrics
        sections.append(self._format_counter(self.process_cpu_seconds))
        sections.append(self._format_gauge(self.process_memory_bytes))
        sections.append(self._format_gauge(self.process_start_time))
        sections.append(self._format_gauge(self.service_info))

        # Custom metrics
        for counter in self.custom_counters.values():
            sections.append(self._format_counter(counter))

        for gauge in self.custom_gauges.values():
            sections.append(self._format_gauge(gauge))

        for histogram in self.custom_histograms.values():
            sections.append(self._format_histogram(histogram))

        return '\n\n'.join(sections) + '\n'

    def get_json_metrics(self) -> Dict[str, Any]:
        """
        Get metrics in JSON format (alternative to Prometheus format).

        Returns:
            Dict with all metrics
        """
        self.update_resource_metrics()

        return {
            'service': self.service_name,
            'version': self.version,
            'uptime_seconds': time.time() - self.start_time,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'http_requests': {
                'total': sum(v for _, v in self.http_requests_total.get_samples()),
                'by_endpoint': dict(self.http_requests_total.get_samples())
            },
            'error_rates': dict(self.error_rate.get_samples()),
            'in_flight_requests': sum(v for _, v in self.http_requests_in_flight.get_samples()),
            'process': {
                'memory_rss_bytes': next((v for l, v in self.process_memory_bytes.get_samples()
                                         if l.get('type') == 'rss'), 0),
                'memory_vms_bytes': next((v for l, v in self.process_memory_bytes.get_samples()
                                         if l.get('type') == 'vms'), 0),
                'start_time': self.start_time
            }
        }


def create_metrics_blueprint(metrics: PrometheusMetrics) -> Blueprint:
    """
    Create a Flask blueprint with /metrics endpoint.

    Args:
        metrics: PrometheusMetrics instance

    Returns:
        Flask Blueprint with /metrics endpoint
    """
    bp = Blueprint('prometheus_metrics', __name__)

    @bp.route('/metrics', methods=['GET'])
    def prometheus_metrics():
        """Prometheus metrics endpoint."""
        output = metrics.get_prometheus_output()
        return Response(
            output,
            mimetype='text/plain; version=0.0.4; charset=utf-8'
        )

    @bp.route('/metrics/json', methods=['GET'])
    def json_metrics():
        """JSON metrics endpoint (alternative format)."""
        from flask import jsonify
        return jsonify(metrics.get_json_metrics())

    return bp


class MetricsMiddleware:
    """
    WSGI middleware for automatic request metrics collection.

    Usage:
        metrics = PrometheusMetrics(service_name='my-service')
        app.wsgi_app = MetricsMiddleware(app.wsgi_app, metrics)
    """

    def __init__(self, app, metrics: PrometheusMetrics,
                 exclude_paths: List[str] = None):
        self.app = app
        self.metrics = metrics
        self.exclude_paths = set(exclude_paths or ['/metrics', '/health', '/health/live'])

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '/')
        method = environ.get('REQUEST_METHOD', 'GET')

        # Skip metrics collection for excluded paths
        if path in self.exclude_paths:
            return self.app(environ, start_response)

        # Track in-flight requests
        self.metrics.request_in_flight_inc(method)
        start_time = time.time()

        # Capture response status
        response_status = [200]  # Default

        def custom_start_response(status, response_headers, exc_info=None):
            response_status[0] = int(status.split()[0])
            return start_response(status, response_headers, exc_info)

        try:
            response = self.app(environ, custom_start_response)
            return response
        finally:
            duration = time.time() - start_time
            self.metrics.record_request(path, method, response_status[0], duration)
            self.metrics.request_in_flight_dec(method)


# Convenience function for Flask apps
def setup_prometheus_metrics(app, service_name: str, version: str = '1.0.0',
                            exclude_paths: List[str] = None) -> PrometheusMetrics:
    """
    Set up Prometheus metrics for a Flask application.

    Args:
        app: Flask application
        service_name: Name of the service
        version: Service version
        exclude_paths: Paths to exclude from metrics collection

    Returns:
        PrometheusMetrics instance

    Usage:
        from shared.utils.prometheus_metrics import setup_prometheus_metrics

        app = Flask(__name__)
        metrics = setup_prometheus_metrics(app, 'admin-dashboard', '1.0.0')
    """
    metrics = PrometheusMetrics(service_name=service_name, version=version)

    # Register metrics blueprint
    bp = create_metrics_blueprint(metrics)
    app.register_blueprint(bp)

    # Add middleware for automatic request tracking
    app.wsgi_app = MetricsMiddleware(app.wsgi_app, metrics, exclude_paths)

    logger.info(f"Prometheus metrics enabled for {service_name}")

    return metrics
