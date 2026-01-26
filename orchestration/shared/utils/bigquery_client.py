# shared/utils/bigquery_client.py
"""
BigQuery client utilities for NBA platform
"""

import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from google.cloud import bigquery
from google.cloud.exceptions import NotFound
import pandas as pd

logger = logging.getLogger(__name__)


class BigQueryClient:
    """Centralized BigQuery operations for NBA platform"""
    
    def __init__(self, project_id: str, dataset_id: str = "nba_analytics"):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.dataset_ref = f"{project_id}.{dataset_id}"
    
    def load_json_data(self, table_name: str, data: List[Dict[str, Any]], 
                      write_disposition: str = "WRITE_APPEND") -> bool:
        """
        Load JSON data into BigQuery table
        
        Args:
            table_name: Target table name
            data: List of dictionaries to load
            write_disposition: WRITE_APPEND, WRITE_TRUNCATE, or WRITE_EMPTY
            
        Returns:
            True if successful, False otherwise
        """
        if not data:
            logger.warning(f"No data to load into {table_name}")
            return True
            
        table_id = f"{self.dataset_ref}.{table_name}"
        
        job_config = bigquery.LoadJobConfig(
            write_disposition=write_disposition,
            autodetect=True,
            create_disposition="CREATE_IF_NEEDED"
        )
        
        try:
            job = self.client.load_table_from_json(
                data, table_id, job_config=job_config
            )
            # Wait for completion with timeout to prevent indefinite hangs
            job.result(timeout=60)

            logger.info(f"Loaded {len(data)} rows into {table_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load data into {table_id}: {e}", exc_info=True)
            return False
    
    def query_to_dataframe(self, query: str, 
                          parameters: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
        """
        Execute query and return results as pandas DataFrame
        
        Args:
            query: SQL query string
            parameters: Query parameters for parameterized queries
            
        Returns:
            DataFrame with query results
        """
        job_config = bigquery.QueryJobConfig()
        
        if parameters:
            job_config.query_parameters = [
                bigquery.ScalarQueryParameter(key, "STRING", value)
                for key, value in parameters.items()
            ]
        
        try:
            query_job = self.client.query(query, job_config=job_config)
            df = query_job.to_dataframe()
            logger.info(f"Query returned {len(df)} rows")
            return df
            
        except Exception as e:
            logger.error(f"Query failed: {e}", exc_info=True)
            return pd.DataFrame()
    
    def table_exists(self, table_name: str) -> bool:
        """Check if table exists in the dataset"""
        table_id = f"{self.dataset_ref}.{table_name}"
        try:
            self.client.get_table(table_id)
            return True
        except NotFound:
            return False
    
    def get_table_info(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Get table metadata and statistics"""
        if not self.table_exists(table_name):
            return None
            
        table_id = f"{self.dataset_ref}.{table_name}"
        table = self.client.get_table(table_id)
        
        return {
            "num_rows": table.num_rows,
            "num_bytes": table.num_bytes,
            "created": table.created,
            "modified": table.modified,
            "schema": [{"name": field.name, "type": field.field_type} 
                      for field in table.schema]
        }
    
    def create_table_from_schema(self, table_name: str, 
                                schema: List[Dict[str, str]]) -> bool:
        """
        Create table with explicit schema
        
        Args:
            table_name: Name of table to create
            schema: List of dicts with 'name' and 'type' keys
            
        Returns:
            True if successful
        """
        table_id = f"{self.dataset_ref}.{table_name}"
        
        bq_schema = [
            bigquery.SchemaField(field["name"], field["type"])
            for field in schema
        ]
        
        table = bigquery.Table(table_id, schema=bq_schema)
        
        try:
            table = self.client.create_table(table)
            logger.info(f"Created table {table_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create table {table_id}: {e}", exc_info=True)
            return False
        