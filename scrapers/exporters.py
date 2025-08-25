import json
import os
from google.cloud import storage

class BaseExporter:
    def run(self, data, config, opts):
        raise NotImplementedError("Exporter must implement 'run' method.")

def _prepare_data_for_export(data, config):
    """
    Prepare data for export. Returns (payload, is_binary) tuple.
    Binary data is preserved as-is, JSON data is serialized.
    """
    if isinstance(data, bytes):
        # Binary data (PDFs, images, etc) - return as-is
        return data, True
    elif isinstance(data, (dict, list)):
        # JSON data - serialize it
        indent = 2 if config.get("pretty_print") else None
        return json.dumps(data, indent=indent), False
    else:
        # String data
        return str(data), False

class GCSExporter(BaseExporter):
    """
    Upload scraped data to Google Cloud Storage (GCS).
    Handles both binary (PDF) and text (JSON) data correctly.
    """
    def run(self, data, config, opts):
        # 1) Use explicit bucket from config, or default to raw scraped data bucket
        bucket_name = config.get("bucket", os.environ.get("GCS_BUCKET_RAW", "nba-scraped-data"))

        # 2) Build GCS path from config key + string formatting
        gcs_path = config.get("key", "default.json")
        if "%(" in gcs_path:
            gcs_path = gcs_path % opts

        # 3) Prepare data (preserves binary, serializes JSON)
        payload, is_binary = _prepare_data_for_export(data, config)
        
        # 4) Set appropriate content type
        if is_binary and gcs_path.endswith('.pdf'):
            content_type = "application/pdf"
        elif is_binary:
            content_type = "application/octet-stream"
        else:
            content_type = "application/json"

        # 5) Upload to GCS
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        
        if is_binary:
            # Upload binary data directly
            blob.upload_from_string(payload, content_type=content_type)
        else:
            # Upload text data as UTF-8 encoded bytes
            blob.upload_from_string(payload.encode('utf-8'), content_type=content_type)

        print(f"[GCS Exporter] Uploaded to gs://{bucket_name}/{gcs_path}")

class FileExporter(BaseExporter):
    """
    Write data to a local file.
    Handles both binary (PDF) and text (JSON) data correctly.
    """
    def run(self, data, config, opts):
        # 1) Determine filename
        filename = config.get("filename", "/tmp/default.json")
        if "%(" in filename:
            filename = filename % opts

        # 2) Prepare data (preserves binary, serializes JSON)
        payload, is_binary = _prepare_data_for_export(data, config)

        # 3) Write to file with appropriate mode
        if is_binary:
            # Write binary data in binary mode
            with open(filename, "wb") as f:
                f.write(payload)
        else:
            # Write text data in text mode
            with open(filename, "w", encoding="utf-8") as f:
                f.write(payload)
                
        print(f"[File Exporter] Wrote to {filename}")

class PrintExporter(BaseExporter):
    """
    Print data to the console (useful for debug).
    """
    def run(self, data, config, opts):
        payload, is_binary = _prepare_data_for_export(data, config)
        
        if is_binary:
            print(f"[Binary data: {len(payload)} bytes]")
        else:
            print(payload)

# Registry that maps "type" -> Exporter Class
EXPORTER_REGISTRY = {
    "gcs": GCSExporter,
    "file": FileExporter,
    "print": PrintExporter,
}
