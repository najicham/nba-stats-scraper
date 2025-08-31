#!/usr/bin/env python3
"""
Process the 6 problematic games with corrected GCS data.
"""

import sys
import os
import logging
import json
from google.cloud import storage

# Add the project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from processors.nbacom.nbac_gamebook_processor import NbacGamebookProcessor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GAMES_TO_FIX = [
    "gs://nba-scraped-data/nba-com/gamebooks-data/2024-12-14/20241214-ATLMIL/20250830_194839.json",
    "gs://nba-scraped-data/nba-com/gamebooks-data/2024-12-14/20241214-HOUOKC/20250830_195017.json",
    "gs://nba-scraped-data/nba-com/gamebooks-data/2025-01-23/20250123-SASIND/20250830_195024.json",
    "gs://nba-scraped-data/nba-com/gamebooks-data/2025-01-25/20250125-INDSAS/20250830_195034.json", 
    "gs://nba-scraped-data/nba-com/gamebooks-data/2025-02-20/20250220-PHXSAS/20250830_195041.json",
    "gs://nba-scraped-data/nba-com/gamebooks-data/2025-02-21/20250221-DETSAS/20250830_195047.json"
]

def process_single_game(gcs_file: str):
    processor = NbacGamebookProcessor()
    
    storage_client = storage.Client()
    bucket_name = gcs_file.split('/')[2]
    file_path = '/'.join(gcs_file.split('/')[3:])
    
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_path)
    
    if not blob.exists():
        logger.error(f"File not found: {gcs_file}")
        return False
    
    content = blob.download_as_text()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {gcs_file}: {e}")
        return False
    
    rows = processor.transform_data(data, file_path)
    logger.info(f"Transformed {len(rows)} players from {gcs_file}")
    
    result = processor.load_data(rows)
    
    if result.get('errors'):
        logger.error(f"Failed to load {gcs_file}: {result['errors']}")
        return False
    
    logger.info(f"Successfully processed {gcs_file}: {result.get('rows_processed', len(rows))} rows")
    return True

def main():
    logger.info("Starting fix for 6 problematic games...")
    success_count = 0
    
    for gcs_file in GAMES_TO_FIX:
        try:
            logger.info(f"Processing: {gcs_file}")
            if process_single_game(gcs_file):
                success_count += 1
                logger.info(f"✅ Successfully processed {gcs_file}")
            else:
                logger.error(f"❌ Failed to process {gcs_file}")
        except Exception as e:
            logger.error(f"Error processing {gcs_file}: {e}")
    
    logger.info(f"Fix complete: {success_count}/{len(GAMES_TO_FIX)} games processed successfully")

if __name__ == "__main__":
    main()