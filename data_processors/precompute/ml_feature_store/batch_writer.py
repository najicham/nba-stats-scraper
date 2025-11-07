# File: data_processors/precompute/ml_feature_store/batch_writer.py
"""
Batch Writer - Write Features to BigQuery

Writes feature vectors in batches of 100 rows with retry logic.

Strategy:
1. DELETE existing records for game_date
2. Split rows into batches of 100
3. Write each batch with load job
4. Retry failed batches (max 3 attempts)
5. Handle streaming buffer gracefully
"""

import logging
import time
import io
import json
from datetime import datetime, date
from typing import Dict, List
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class BatchWriter:
    """Write features to BigQuery in batches."""
    
    # Configuration
    BATCH_SIZE = 100
    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 5
    
    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize batch writer.
        
        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
        """
        self.bq_client = bq_client
        self.project_id = project_id
    
    def write_batch(self, rows: List[Dict], dataset_id: str, table_name: str,
                   game_date: date) -> Dict:
        """
        Write feature rows to BigQuery in batches.
        
        Args:
            rows: List of feature records
            dataset_id: Target dataset (nba_predictions)
            table_name: Target table (ml_feature_store_v2)
            game_date: Game date (for DELETE filtering)
            
        Returns:
            Dict with write stats:
                - rows_processed: int
                - rows_failed: int
                - batches_written: int
                - batches_failed: int
                - errors: List[str]
        """
        if not rows:
            logger.warning("No rows to write")
            return {
                'rows_processed': 0,
                'rows_failed': 0,
                'batches_written': 0,
                'batches_failed': 0,
                'errors': []
            }
        
        table_id = f"{self.project_id}.{dataset_id}.{table_name}"
        
        # Step 1: Delete existing records for game_date
        delete_success = self._delete_existing_data(table_id, game_date)
        if not delete_success:
            logger.warning("DELETE failed (likely streaming buffer), continuing with INSERT")
        
        # Step 2: Split into batches
        batches = self._split_into_batches(rows, self.BATCH_SIZE)
        logger.info(f"Split {len(rows)} rows into {len(batches)} batches of {self.BATCH_SIZE}")
        
        # Step 3: Write each batch
        results = {
            'rows_processed': 0,
            'rows_failed': 0,
            'batches_written': 0,
            'batches_failed': 0,
            'errors': []
        }
        
        for batch_idx, batch_rows in enumerate(batches):
            logger.info(f"Writing batch {batch_idx + 1}/{len(batches)} ({len(batch_rows)} rows)")
            
            success, error = self._write_single_batch(table_id, batch_rows)
            
            if success:
                results['rows_processed'] += len(batch_rows)
                results['batches_written'] += 1
            else:
                results['rows_failed'] += len(batch_rows)
                results['batches_failed'] += 1
                results['errors'].append(f"Batch {batch_idx + 1}: {error}")
                logger.error(f"Batch {batch_idx + 1} failed: {error}")
        
        # Log summary
        success_rate = (results['rows_processed'] / len(rows) * 100) if len(rows) > 0 else 0
        logger.info(f"Write complete: {results['rows_processed']}/{len(rows)} rows ({success_rate:.1f}% success)")
        
        if results['errors']:
            logger.error(f"Write errors: {results['errors']}")
        
        return results
    
    def _delete_existing_data(self, table_id: str, game_date: date) -> bool:
        """
        Delete existing records for game_date.
        
        Args:
            table_id: Full table ID (project.dataset.table)
            game_date: Game date to delete
            
        Returns:
            bool: True if delete successful, False if streaming buffer blocked
        """
        delete_query = f"""
        DELETE FROM `{table_id}`
        WHERE game_date = '{game_date}'
        """
        
        try:
            logger.info(f"Deleting existing records for {game_date}")
            delete_job = self.bq_client.query(delete_query)
            delete_job.result()
            
            if delete_job.num_dml_affected_rows is not None:
                logger.info(f"✅ Deleted {delete_job.num_dml_affected_rows} existing rows")
            else:
                logger.info(f"✅ Delete completed for {game_date}")
            
            return True
            
        except Exception as e:
            error_msg = str(e).lower()
            if "streaming buffer" in error_msg:
                logger.warning("⚠️ Delete blocked by streaming buffer (expected in some cases)")
                logger.info("Duplicates will be cleaned up on next run")
                return False
            else:
                logger.error(f"Delete failed with unexpected error: {e}")
                raise e
    
    def _split_into_batches(self, rows: List[Dict], batch_size: int) -> List[List[Dict]]:
        """
        Split rows into batches.
        
        Args:
            rows: Full list of rows
            batch_size: Size of each batch
            
        Returns:
            List of batches (each batch is a list of rows)
        """
        batches = []
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            batches.append(batch)
        return batches
    
    def _write_single_batch(self, table_id: str, rows: List[Dict]) -> tuple:
        """
        Write a single batch with retry logic.
        
        Args:
            table_id: Full table ID
            rows: Batch of rows to write
            
        Returns:
            tuple: (success: bool, error: str)
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                # Get table schema
                try:
                    table = self.bq_client.get_table(table_id)
                    table_schema = table.schema
                except Exception as schema_e:
                    logger.warning(f"Could not get table schema: {schema_e}")
                    table_schema = None
                
                # Convert to NDJSON
                ndjson_data = "\n".join(json.dumps(row) for row in rows)
                ndjson_bytes = ndjson_data.encode('utf-8')
                
                # Configure load job
                job_config = bigquery.LoadJobConfig(
                    schema=table_schema,
                    source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                    autodetect=False
                )
                
                # Execute load job
                load_job = self.bq_client.load_table_from_file(
                    io.BytesIO(ndjson_bytes),
                    table_id,
                    job_config=job_config
                )
                
                # Wait for completion
                load_job.result()
                
                logger.info(f"✅ Batch written successfully ({len(rows)} rows)")
                return True, None
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Streaming buffer error - don't retry
                if "streaming buffer" in error_msg:
                    logger.warning(f"⚠️ Batch blocked by streaming buffer ({len(rows)} rows skipped)")
                    return False, "Streaming buffer conflict"
                
                # Other errors - retry
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Batch write attempt {attempt + 1} failed: {e}")
                    logger.info(f"Retrying in {self.RETRY_DELAY_SECONDS} seconds...")
                    time.sleep(self.RETRY_DELAY_SECONDS)
                else:
                    logger.error(f"Batch write failed after {self.MAX_RETRIES} attempts: {e}")
                    return False, str(e)
        
        return False, "Max retries exceeded"
