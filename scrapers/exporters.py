import json
import os
from google.cloud import storage
import google.auth
from google.auth.exceptions import DefaultCredentialsError

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
    Enhanced with proper authentication handling and smart content-type detection.
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
        
        # 4) Set appropriate content type with smart detection
        if is_binary and gcs_path.endswith('.pdf'):
            content_type = "application/pdf"
        elif is_binary and gcs_path.endswith('.json'):
            # Smart fix: binary data to .json file is JSON content
            content_type = "application/json"
        elif is_binary:
            content_type = "application/octet-stream"
        else:
            content_type = "application/json"

        # 5) Create GCS client with proper authentication handling
        client = self._create_gcs_client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(gcs_path)
        
        if is_binary:
            # Upload binary data directly
            blob.upload_from_string(payload, content_type=content_type)
        else:
            # Upload text data as UTF-8 encoded bytes
            blob.upload_from_string(payload.encode('utf-8'), content_type=content_type)

        print(f"[GCS Exporter] Uploaded to gs://{bucket_name}/{gcs_path} (content-type: {content_type})")

    def _create_gcs_client(self):
        """
        Create GCS client with robust authentication handling.
        
        Priority order:
        1. GOOGLE_APPLICATION_CREDENTIALS environment variable (service account)
        2. Application Default Credentials (gcloud auth application-default login)
        3. Service account file in current directory
        4. Fail with helpful error message
        """
        try:
            # Try 1: Use environment variable or application default credentials
            if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                # No explicit service account, try application default credentials
                credentials, project = google.auth.default()
                return storage.Client(credentials=credentials, project=project)
            else:
                # Service account path is set, use it
                return storage.Client()
                
        except DefaultCredentialsError:
            # Try 2: Look for service account file in current directory
            service_account_files = [
                "./service-account-dev.json",
                "./service-account-prod.json", 
                "./service-account.json"
            ]
            
            for sa_file in service_account_files:
                if os.path.exists(sa_file):
                    print(f"[GCS Exporter] Using service account: {sa_file}")
                    return storage.Client.from_service_account_json(sa_file)
            
            # Try 3: Check for application default credentials file
            adc_path = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
            if os.path.exists(adc_path):
                print(f"[GCS Exporter] Using application default credentials: {adc_path}")
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = adc_path
                return storage.Client()
            
            # All methods failed
            raise Exception(
                "GCS authentication failed. Please run one of:\n"
                "  1. gcloud auth application-default login\n"
                "  2. Place service account JSON file in current directory\n"
                "  3. Set GOOGLE_APPLICATION_CREDENTIALS environment variable"
            )

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