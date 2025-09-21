#!/usr/bin/env python3
"""
File: scripts/fix_name_normalization.py

Database Name Normalization Fix Script

This script fixes player_lookup values in the database to use the updated
normalization function that properly handles periods and other characters.

Usage:
    python scripts/fix_name_normalization.py --dry-run
    python scripts/fix_name_normalization.py --execute --batch-size 1000
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple
from google.cloud import bigquery
import pandas as pd

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.utils.player_name_normalizer import normalize_name_for_lookup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class NameNormalizationFixer:
    """Fix player_lookup values using updated normalization function."""
    
    def __init__(self, project_id: str = None):
        self.project_id = project_id or os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        
        # Debug: Print the project ID being used
        print(f"DEBUG: Using project_id: '{self.project_id}'")
        
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Tables that need fixing (manually specified for controlled approach)
        self.tables_to_fix = [
            'nba_raw.nbac_gamebook_player_stats',
            # Add other tables here only after their processors are updated
        ]
        
        self.stats = {
            'total_rows_checked': 0,
            'rows_needing_update': 0,
            'rows_updated': 0,
            'errors': 0
        }
    
    def find_tables_with_player_lookup(self) -> List[str]:
        """Dynamically find all tables with player_lookup columns."""
        # Query each dataset's INFORMATION_SCHEMA individually since global INFORMATION_SCHEMA doesn't work
        datasets_to_check = ['nba_raw', 'nba_processed', 'nba_analytics']
        all_tables = []
        
        for dataset in datasets_to_check:
            query = f"""
            SELECT 
                '{dataset}' as table_schema,
                table_name,
                column_name
            FROM `{self.project_id}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
            WHERE column_name = 'player_lookup'
            ORDER BY table_name
            """
            
            try:
                results = self.bq_client.query(query).to_dataframe()
                if not results.empty:
                    dataset_tables = [f"{dataset}.{row['table_name']}" for _, row in results.iterrows()]
                    all_tables.extend(dataset_tables)
                    logger.info(f"Found {len(dataset_tables)} tables with player_lookup in {dataset}")
            except Exception as e:
                # Dataset might not exist, which is fine
                logger.info(f"Dataset {dataset} not found or no access: {e}")
                continue
        
        logger.info(f"Total: {len(all_tables)} tables with player_lookup columns:")
        for table in all_tables:
            logger.info(f"  - {table}")
        
        return all_tables
    
    def analyze_normalization_differences(self, table_name: str) -> pd.DataFrame:
        """Find rows where old vs new normalization produces different results."""
        
        # For now, assume player_name is the source column (specific to gamebook table)
        # This can be made configurable later when we add other tables
        query = f"""
        SELECT 
            player_name as source_name,
            player_lookup as current_lookup
        FROM `{table_name}`
        WHERE player_name IS NOT NULL 
        AND player_name != ''
        AND player_lookup IS NOT NULL
        GROUP BY player_name, player_lookup
        ORDER BY player_name
        """
        
        try:
            results = self.bq_client.query(query).to_dataframe()
            
            if results.empty:
                logger.warning(f"No data found in {table_name}")
                return pd.DataFrame()
            
            # Calculate new normalization for each unique name
            results['new_lookup'] = results['source_name'].apply(normalize_name_for_lookup)
            
            # Find differences
            differences = results[results['current_lookup'] != results['new_lookup']].copy()
            
            logger.info(f"Table {table_name}:")
            logger.info(f"  Total unique names: {len(results)}")
            logger.info(f"  Names needing update: {len(differences)}")
            
            return differences
            
        except Exception as e:
            logger.error(f"Error analyzing {table_name}: {e}")
            return pd.DataFrame()
    
    def preview_changes(self, differences: pd.DataFrame, table_name: str, limit: int = 10):
        """Preview the changes that would be made."""
        if differences.empty:
            logger.info(f"No changes needed for {table_name}")
            return
        
        logger.info(f"\nPreview of changes for {table_name} (showing first {limit}):")
        logger.info("-" * 80)
        
        for idx, row in differences.head(limit).iterrows():
            logger.info(f"Name: '{row['source_name']}'")
            logger.info(f"  Current: '{row['current_lookup']}'")
            logger.info(f"  New:     '{row['new_lookup']}'")
            logger.info("")
        
        if len(differences) > limit:
            logger.info(f"... and {len(differences) - limit} more changes")
    
    def update_table_normalization(self, table_name: str, batch_size: int = 1000, dry_run: bool = True) -> Dict:
        """Update player_lookup values in a specific table using Python normalization."""
        
        # Get differences
        differences = self.analyze_normalization_differences(table_name)
        
        if differences.empty:
            return {'updated': 0, 'errors': 0}
        
        if dry_run:
            self.preview_changes(differences, table_name)
            return {'updated': 0, 'errors': 0, 'would_update': len(differences)}
        
        # Use Python normalization instead of BigQuery NORMALIZE function
        try:
            logger.info(f"Executing update for {table_name}...")
            
            total_updated = 0
            errors = 0
            
            # Process in batches to avoid memory issues
            for i in range(0, len(differences), batch_size):
                batch = differences.iloc[i:i + batch_size]
                
                # Build individual UPDATE statements using Python normalization
                update_statements = []
                for _, row in batch.iterrows():
                    source_name = row['source_name']
                    current_lookup = row['current_lookup']
                    
                    # Use our Python normalization function
                    correct_lookup = normalize_name_for_lookup(source_name)
                    
                    # Only update if it's actually different
                    if current_lookup != correct_lookup:
                        # Escape single quotes in names
                        escaped_name = source_name.replace("'", "\\'")
                        escaped_lookup = correct_lookup.replace("'", "\\'")
                        
                        update_statements.append(f"""
                        UPDATE `{table_name}`
                        SET player_lookup = '{escaped_lookup}',
                            processed_at = CURRENT_TIMESTAMP()
                        WHERE player_name = '{escaped_name}'
                        """)
                
                # Execute batch updates
                for statement in update_statements:
                    try:
                        job = self.bq_client.query(statement)
                        result = job.result()
                        rows_affected = job.num_dml_affected_rows or 0
                        total_updated += rows_affected
                        
                    except Exception as e:
                        logger.error(f"Error updating name '{source_name}': {e}")
                        errors += 1
                
                logger.info(f"Processed batch {i//batch_size + 1}/{(len(differences)-1)//batch_size + 1}")
            
            logger.info(f"Updated {total_updated} rows in {table_name}")
            self.stats['rows_updated'] += total_updated
            
            return {'updated': total_updated, 'errors': errors}
            
        except Exception as e:
            logger.error(f"Error updating {table_name}: {e}")
            self.stats['errors'] += 1
            return {'updated': 0, 'errors': 1}
    
    def validate_updates(self, table_name: str) -> bool:
        """Validate that updates were applied correctly."""
        
        # Check for any remaining differences
        remaining_differences = self.analyze_normalization_differences(table_name)
        
        if remaining_differences.empty:
            logger.info(f"✅ {table_name}: All normalizations are now correct")
            return True
        else:
            logger.warning(f"⚠️ {table_name}: {len(remaining_differences)} rows still have incorrect normalization")
            self.preview_changes(remaining_differences, table_name, limit=5)
            return False
    
    def run_full_fix(self, dry_run: bool = True, batch_size: int = 1000, 
                     custom_tables: List[str] = None) -> Dict:
        """Run the complete normalization fix process."""
        
        start_time = datetime.now()
        
        # Determine which tables to process
        if custom_tables:
            tables_to_process = custom_tables
        else:
            # Find all tables automatically
            tables_to_process = self.find_tables_with_player_lookup()
        
        logger.info(f"Starting normalization fix {'(DRY RUN)' if dry_run else '(EXECUTING)'}")
        logger.info(f"Processing {len(tables_to_process)} tables")
        
        results = {}
        
        for table_name in tables_to_process:
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing: {table_name}")
            logger.info(f"{'='*60}")
            
            try:
                result = self.update_table_normalization(table_name, batch_size, dry_run)
                results[table_name] = result
                
                # Validate if we actually executed updates
                if not dry_run and result['updated'] > 0:
                    self.validate_updates(table_name)
                    
            except Exception as e:
                logger.error(f"Failed to process {table_name}: {e}")
                results[table_name] = {'updated': 0, 'errors': 1}
                self.stats['errors'] += 1
        
        # Summary
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info(f"\n{'='*60}")
        logger.info("SUMMARY")
        logger.info(f"{'='*60}")
        logger.info(f"Duration: {duration}")
        logger.info(f"Tables processed: {len(tables_to_process)}")
        
        if dry_run:
            total_would_update = sum(r.get('would_update', 0) for r in results.values())
            logger.info(f"Total rows that would be updated: {total_would_update}")
        else:
            logger.info(f"Total rows updated: {self.stats['rows_updated']}")
            logger.info(f"Errors: {self.stats['errors']}")
        
        # Detailed results
        for table_name, result in results.items():
            if dry_run and result.get('would_update', 0) > 0:
                logger.info(f"  {table_name}: {result['would_update']} rows need updating")
            elif not dry_run and result.get('updated', 0) > 0:
                logger.info(f"  {table_name}: {result['updated']} rows updated")
        
        return results


def main():
    parser = argparse.ArgumentParser(description='Fix player name normalization in database')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Preview changes without executing (default)')
    parser.add_argument('--execute', action='store_true',
                       help='Execute the updates (use with caution)')
    parser.add_argument('--batch-size', type=int, default=1000,
                       help='Batch size for updates (default: 1000)')
    parser.add_argument('--tables', nargs='+',
                       help='Specific tables to process (e.g., nba_raw.nbac_gamebook_player_stats)')
    parser.add_argument('--project-id', type=str,
                       help='GCP project ID (defaults to GCP_PROJECT_ID env var)')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.execute and args.dry_run:
        logger.error("Cannot specify both --execute and --dry-run")
        sys.exit(1)
    
    # Default to dry run if neither specified
    dry_run = not args.execute
    
    if dry_run:
        logger.info("Running in DRY RUN mode (no changes will be made)")
    else:
        logger.warning("Running in EXECUTE mode - changes will be made to the database!")
        response = input("Are you sure you want to proceed? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            logger.info("Aborted by user")
            sys.exit(0)
    
    # Create fixer instance
    fixer = NameNormalizationFixer(project_id=args.project_id)
    
    # Run the fix
    try:
        results = fixer.run_full_fix(
            dry_run=dry_run,
            batch_size=args.batch_size,
            custom_tables=args.tables
        )
        
        if not dry_run:
            logger.info("✅ Name normalization fix completed successfully!")
        else:
            logger.info("✅ Dry run completed. Use --execute to apply changes.")
            
    except Exception as e:
        logger.error(f"❌ Fix failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()