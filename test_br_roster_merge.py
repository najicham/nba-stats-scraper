#!/usr/bin/env python3
"""
Test script for Basketball Reference Roster MERGE pattern.
Validates the MERGE logic works correctly before deploying.
"""

import os
import sys
from datetime import date, datetime
from google.cloud import bigquery

# Set up path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_merge_pattern():
    """Test MERGE pattern with sample roster data."""

    project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
    client = bigquery.Client(project=project_id)

    table_id = f"{project_id}.nba_raw.br_rosters_current"
    temp_table_id = f"{project_id}.nba_raw.br_rosters_temp_TEST"

    print("🧪 Testing Basketball Reference Roster MERGE Pattern")
    print("=" * 60)

    # Step 1: Create test data
    print("\n1️⃣ Creating test data...")
    test_data = [
        {
            "season_year": 2024,
            "season_display": "2024-25",
            "team_abbrev": "TEST",
            "player_full_name": "LeBron James",
            "player_last_name": "James",
            "player_normalized": "lebron-james",
            "player_lookup": "lebronjames",
            "position": "F",
            "jersey_number": "23",
            "height": "6-9",
            "weight": "250",
            "birth_date": "1984-12-30",
            "college": "None",
            "experience_years": 21,
            "first_seen_date": date.today().isoformat(),
            "last_scraped_date": date.today().isoformat(),
            "source_file_path": "test/br/roster/TEST/2024.json",
            "processed_at": datetime.utcnow().isoformat(),
            "data_hash": "test_hash_1"
        },
        {
            "season_year": 2024,
            "season_display": "2024-25",
            "team_abbrev": "TEST",
            "player_full_name": "Anthony Davis",
            "player_last_name": "Davis",
            "player_normalized": "anthony-davis",
            "player_lookup": "anthonydavis",
            "position": "F-C",
            "jersey_number": "3",
            "height": "6-10",
            "weight": "253",
            "birth_date": "1993-03-11",
            "college": "Kentucky",
            "experience_years": 12,
            "first_seen_date": date.today().isoformat(),
            "last_scraped_date": date.today().isoformat(),
            "source_file_path": "test/br/roster/TEST/2024.json",
            "processed_at": datetime.utcnow().isoformat(),
            "data_hash": "test_hash_2"
        }
    ]
    print(f"✅ Created {len(test_data)} test players")

    try:
        # Step 2: Load to temp table
        print("\n2️⃣ Loading test data to temp table...")

        # Clean up any existing temp table
        client.delete_table(temp_table_id, not_found_ok=True)

        # Get target table schema
        target_table = client.get_table(table_id)

        # Configure load job
        job_config = bigquery.LoadJobConfig(
            schema=target_table.schema,
            autodetect=False,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
        )

        # Load to temp table
        load_job = client.load_table_from_json(
            test_data,
            temp_table_id,
            job_config=job_config
        )
        load_job.result(timeout=60)
        print(f"✅ Loaded {len(test_data)} rows to temp table")

        # Step 3: Execute MERGE
        print("\n3️⃣ Executing MERGE from temp to main table...")

        merge_query = f"""
        MERGE `{table_id}` AS target
        USING `{temp_table_id}` AS source
        ON target.season_year = source.season_year
           AND target.team_abbrev = source.team_abbrev
           AND target.player_lookup = source.player_lookup
        WHEN MATCHED THEN
          UPDATE SET
            player_full_name = source.player_full_name,
            player_last_name = source.player_last_name,
            player_normalized = source.player_normalized,
            position = source.position,
            jersey_number = source.jersey_number,
            height = source.height,
            weight = source.weight,
            birth_date = source.birth_date,
            college = source.college,
            experience_years = source.experience_years,
            last_scraped_date = source.last_scraped_date,
            source_file_path = source.source_file_path,
            processed_at = source.processed_at,
            data_hash = source.data_hash
        WHEN NOT MATCHED THEN
          INSERT (
            season_year, season_display, team_abbrev,
            player_full_name, player_last_name, player_normalized, player_lookup,
            position, jersey_number, height, weight, birth_date, college, experience_years,
            first_seen_date, last_scraped_date, source_file_path, processed_at, data_hash
          )
          VALUES (
            source.season_year, source.season_display, source.team_abbrev,
            source.player_full_name, source.player_last_name, source.player_normalized, source.player_lookup,
            source.position, source.jersey_number, source.height, source.weight,
            source.birth_date, source.college, source.experience_years,
            COALESCE(source.first_seen_date, source.last_scraped_date),
            source.last_scraped_date, source.source_file_path, source.processed_at, source.data_hash
          )
        """

        query_job = client.query(merge_query)
        result = query_job.result(timeout=60)

        rows_affected = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0
        print(f"✅ MERGE complete: {rows_affected} rows affected")

        # Step 4: Verify results
        print("\n4️⃣ Verifying MERGE results...")

        verify_query = f"""
        SELECT
            player_full_name,
            position,
            jersey_number,
            experience_years,
            last_scraped_date,
            first_seen_date
        FROM `{table_id}`
        WHERE season_year = 2024
          AND team_abbrev = 'TEST'
        ORDER BY player_full_name
        """

        results = list(client.query(verify_query).result())

        if len(results) != len(test_data):
            print(f"❌ FAILED: Expected {len(test_data)} players, found {len(results)}")
            return False

        print(f"✅ Verified {len(results)} players in main table:")
        for row in results:
            print(f"   - {row.player_full_name}: {row.position}, #{row.jersey_number}, {row.experience_years} years")

        # Step 5: Test UPDATE scenario (run MERGE again with updated data)
        print("\n5️⃣ Testing UPDATE scenario (second MERGE with same players)...")

        # Modify test data (update position for LeBron)
        test_data[0]["position"] = "F-G"  # Changed position
        test_data[0]["processed_at"] = datetime.utcnow().isoformat()

        # Reload to temp table
        client.delete_table(temp_table_id, not_found_ok=True)
        load_job = client.load_table_from_json(
            test_data,
            temp_table_id,
            job_config=job_config
        )
        load_job.result(timeout=60)

        # Execute MERGE again
        query_job = client.query(merge_query)
        result = query_job.result(timeout=60)
        rows_affected = result.num_dml_affected_rows if hasattr(result, 'num_dml_affected_rows') else 0
        print(f"✅ Second MERGE complete: {rows_affected} rows affected")

        # Verify update
        verify_update_query = f"""
        SELECT player_full_name, position
        FROM `{table_id}`
        WHERE season_year = 2024
          AND team_abbrev = 'TEST'
          AND player_lookup = 'lebronjames'
        """

        update_results = list(client.query(verify_update_query).result())
        if update_results and update_results[0].position == "F-G":
            print(f"✅ UPDATE verified: LeBron's position updated to {update_results[0].position}")
        else:
            print(f"❌ FAILED: Position not updated correctly")
            return False

        # Step 6: Clean up test data
        print("\n6️⃣ Cleaning up test data...")

        # Delete test rows
        cleanup_query = f"""
        DELETE FROM `{table_id}`
        WHERE season_year = 2024
          AND team_abbrev = 'TEST'
        """
        client.query(cleanup_query).result()

        # Delete temp table
        client.delete_table(temp_table_id, not_found_ok=True)

        print("✅ Cleanup complete")

        print("\n" + "=" * 60)
        print("🎉 ALL TESTS PASSED! MERGE pattern works correctly.")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        print(f"Error type: {type(e).__name__}")

        # Try to clean up on failure
        try:
            client.delete_table(temp_table_id, not_found_ok=True)
            cleanup_query = f"""
            DELETE FROM `{table_id}`
            WHERE season_year = 2024 AND team_abbrev = 'TEST'
            """
            client.query(cleanup_query).result()
        except Exception:
            pass

        return False


if __name__ == "__main__":
    success = test_merge_pattern()
    sys.exit(0 if success else 1)
