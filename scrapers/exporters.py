import json
import os
from google.cloud import storage

class BaseExporter:
    def run(self, data, config, opts):
        raise NotImplementedError("Exporter must implement 'run' method.")

def _convert_data_to_string(data, config):
    """
    Convert 'data' (dict, list, bytes, or str) to a UTF-8 string.
    If data is dict/list and 'pretty_print' is True, use indentation.
    """
    indent = None
    if config.get("pretty_print"):
        # you could also read an integer from config.get("indent") if you want custom levels
        indent = 2

    if isinstance(data, (dict, list)):
        # Return JSON with optional indentation
        return json.dumps(data, indent=indent)
    elif isinstance(data, bytes):
        # Attempt to decode bytes to a UTF-8 string
        return data.decode("utf-8", errors="ignore")
    else:
        # E.g., if already a string
        return str(data)

class GCSExporter(BaseExporter):
    """
    Upload data to Google Cloud Storage (GCS).
    """
    def run(self, data, config, opts):
        # 1) Determine bucket name
        bucket_name = os.environ.get("BUCKET_NAME", "my-default-bucket")
        if "bucket" in config:
            bucket_name = config["bucket"]

        # 2) Build GCS path from config key + string formatting
        gcs_path = config.get("key", "default.json")
        if "%(" in gcs_path:
            gcs_path = gcs_path % opts

        # 3) Convert data to string
        payload = _convert_data_to_string(data, config)

        # 4) Upload to GCS with a default content_type
        #    If you want to override, you could do config.get("mime_type", "application/json")
        content_type = "application/json"

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        blob.upload_from_string(payload, content_type=content_type)

        print(f"[GCS Exporter] Uploaded to gs://{bucket_name}/{gcs_path}")

class FileExporter(BaseExporter):
    """
    Write data to a local file.
    """
    def run(self, data, config, opts):
        # 1) Determine filename
        filename = config.get("filename", "/tmp/default.json")
        if "%(" in filename:
            filename = filename % opts

        # 2) Convert data to string
        payload = _convert_data_to_string(data, config)

        # 3) Write to file
        with open(filename, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"[File Exporter] Wrote to {filename}")

class PrintExporter(BaseExporter):
    """
    Print data to the console (useful for debug).
    """
    def run(self, data, config, opts):
        # 1) Convert data to string
        payload = _convert_data_to_string(data, config)

        # 2) Print to console
        print(payload)

# If you have Slack or other exporters, define them similarly:
# class SlackExporter(BaseExporter):
#     def run(self, data, config, opts):
#         ...

# Finally, define a registry that maps "type" -> Exporter Class
EXPORTER_REGISTRY = {
    "gcs": GCSExporter,
    "file": FileExporter,
    "print": PrintExporter,
}
