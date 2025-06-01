# scrapers/exporters.py

import json
import os
from google.cloud import storage

class BaseExporter:
    """
    A base class for all exporters.
    Child classes must implement 'run(data, config, opts)'.
    """
    def run(self, data, config, opts):
        raise NotImplementedError("Exporter must implement 'run' method.")

class GCSExporter(BaseExporter):
    """
    Upload data to Google Cloud Storage (GCS).
    """
    def run(self, data, config, opts):
        bucket_name = os.environ.get("BUCKET_NAME", "my-default-bucket")
        if "bucket" in config:
            bucket_name = config["bucket"]

        # If config['key'] has placeholders like "%(gamedate)s", do string formatting:
        gcs_path = config.get("key", "default.json")
        if "%(" in gcs_path:
            gcs_path = gcs_path % opts

        # Convert data to string
        if isinstance(data, (dict, list)):
            data_str = json.dumps(data)
        elif isinstance(data, bytes):
            data_str = data.decode("utf-8", errors="ignore")
        else:
            data_str = str(data)

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(data_str, content_type="application/json")

        print(f"[GCS Exporter] Uploaded to gs://{bucket_name}/{gcs_path}")


class FileExporter(BaseExporter):
    """
    Write data to a local file.
    """
    def run(self, data, config, opts):
        filename = config.get("filename", "/tmp/default.json")
        if "%(" in filename:
            filename = filename % opts

        # Convert data to string
        if isinstance(data, (dict, list)):
            content = json.dumps(data, indent=4)
        elif isinstance(data, bytes):
            content = data.decode("utf-8", errors="ignore")
        else:
            content = str(data)

        with open(filename, "w") as f:
            f.write(content)
        print(f"[File Exporter] Wrote to {filename}")


class PrintExporter(BaseExporter):
    """
    Print data to the console (useful for debug).
    """
    def run(self, data, config, opts):
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=4))
        elif isinstance(data, bytes):
            print(data.decode("utf-8", errors="ignore"))
        else:
            print(str(data))


# If you have Slack or other exporters, define them similarly:
# class SlackExporter(BaseExporter):
#     def run(self, data, config, opts):
#         ...

# Finally, define a registry that maps "type" -> Exporter Class
EXPORTER_REGISTRY = {
    "gcs": GCSExporter,
    "file": FileExporter,
    "print": PrintExporter,
    # "slack": SlackExporter,
    # etc.
}
