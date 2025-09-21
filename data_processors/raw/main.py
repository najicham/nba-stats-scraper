# processors/main.py - Practical implementation

class NBADataProcessor:
    """
    ORCHESTRATOR ROLE:
    - Receives Pub/Sub messages when scrapers finish
    - Loads raw JSON from GCS into BigQuery
    - Triggers BigQuery SQL jobs for analysis
    - Writes results to Firestore for serving
    
    DOES NOT DO:
    - Heavy pandas operations
    - Complex data transformations
    - In-memory processing of large datasets
    """
    
    def __init__(self):
        self.bq_client = bigquery.Client()
        self.firestore_client = firestore.Client()
        self.storage_client = storage.Client()
    
    def process_scraped_data(self, message):
        """
        Called when Pub/Sub message arrives:
        {"bucket": "raw-data", "file": "odds/2025-01-15/abc123.json"}
        """
        
        # 1. Load raw JSON to BigQuery (just a load job)
        self.load_gcs_to_bigquery(message['file'])
        
        # 2. Run SQL analysis in BigQuery (not in Python)
        self.run_player_analysis_sql()
        
        # 3. Get results and write to Firestore (small dataset)
        results = self.get_analysis_results()
        self.update_firestore(results)
        
        # 4. Trigger report generation
        self.trigger_report_generation()
    
    def load_gcs_to_bigquery(self, gcs_file):
        """Simple BigQuery load job - no processing"""
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=True,
        )
        
        # BigQuery does the parsing, not Python
        load_job = self.bq_client.load_table_from_uri(
            f"gs://raw-data/{gcs_file}",
            "nba_analytics.raw_odds_events",
            job_config=job_config
        )
        load_job.result()  # Wait for completion
    
    def run_player_analysis_sql(self):
        """Run SQL in BigQuery - not Python computation"""
        sql = """
        INSERT INTO nba_analytics.player_prop_analysis
        SELECT 
            player_name,
            AVG(points_over_under) as avg_line,
            COUNT(*) as games_count,
            AVG(actual_points) as avg_actual,
            CURRENT_TIMESTAMP() as processed_at
        FROM nba_analytics.raw_odds_events
        WHERE DATE(game_date) = CURRENT_DATE()
        GROUP BY player_name
        """
        
        # BigQuery runs the SQL, not Python
        query_job = self.bq_client.query(sql)
        query_job.result()  # Wait for completion
    
    def update_firestore(self, results):
        """Write small results to Firestore for serving"""
        # Only today's hot data, not historical
        for player in results:
            doc_ref = self.firestore_client.collection('player_props').document(player['id'])
            doc_ref.set({
                'avg_line': player['avg_line'],
                'games_count': player['games_count'],
                'last_updated': firestore.SERVER_TIMESTAMP,
                'ttl': datetime.now() + timedelta(days=3)  # Auto-expire
            })
