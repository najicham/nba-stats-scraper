FROM google/cloud-sdk:slim

# Install required utilities
RUN apt-get update && \
    apt-get install -y bc jq && \
    rm -rf /var/lib/apt/lists/*

# Copy monitoring scripts (from root context)
COPY monitor_feature_staleness.sh /monitor_feature_staleness.sh
COPY monitor_confidence_drift.sh /monitor_confidence_drift.sh
COPY send_daily_summary.sh /send_daily_summary.sh

# Make scripts executable
RUN chmod +x /monitor_feature_staleness.sh /monitor_confidence_drift.sh /send_daily_summary.sh

# Default entrypoint
ENTRYPOINT ["/bin/bash"]
