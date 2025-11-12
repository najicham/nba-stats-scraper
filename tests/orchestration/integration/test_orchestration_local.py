#!/usr/bin/env python3
"""
Local Integration Test Script for Phase 1 Orchestration - FIXED VERSION

Path: tests/orchestration/integration/test_orchestration_local.py
"""

import sys
import os
import argparse
from datetime import datetime
import pytz
from typing import Dict, Any

# Add project root to path (3 levels up from integration test location)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

# Color codes for output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(text: str):
    """Print formatted header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'=' * 70}{Colors.END}\n")


def print_success(text: str):
    """Print success message."""
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")


def print_error(text: str):
    """Print error message."""
    print(f"{Colors.RED}❌ {text}{Colors.END}")


def print_info(text: str):
    """Print info message."""
    print(f"{Colors.YELLOW}ℹ️  {text}{Colors.END}")


def test_registry() -> bool:
    """Test scraper registry functionality."""
    print_header("TEST 1: Scraper Registry")
    
    try:
        from scrapers.registry import (
            SCRAPER_REGISTRY,
            list_scrapers,
            scraper_exists,
            get_scraper_info,
            get_scrapers_by_group
        )
        
        # Test 1: Registry exists and has scrapers
        print("Test 1.1: Checking registry...")
        scraper_count = len(SCRAPER_REGISTRY)
        print_success(f"Registry loaded with {scraper_count} scrapers")
        
        # Test 2: List scrapers
        print("\nTest 1.2: Listing scrapers...")
        scrapers = list_scrapers()
        print_success(f"list_scrapers() returned {len(scrapers)} scrapers")
        print_info(f"Sample scrapers: {scrapers[:5]}")
        
        # Test 3: Check specific scrapers exist
        print("\nTest 1.3: Checking specific scrapers...")
        test_scrapers = ['oddsa_events_his', 'bdl_games', 'nbac_schedule_api']
        for scraper in test_scrapers:
            if scraper_exists(scraper):
                print_success(f"✓ {scraper} exists")
            else:
                print_error(f"✗ {scraper} not found")
                return False
        
        # Test 4: Get scraper info
        print("\nTest 1.4: Getting scraper info...")
        info = get_scraper_info('oddsa_events_his')
        print_success(f"Got info for oddsa_events_his:")
        print_info(f"  Module: {info['module']}")
        print_info(f"  Class: {info['class']}")
        
        # Test 5: Get scrapers by group
        print("\nTest 1.5: Getting scrapers by group...")
        odds_scrapers = get_scrapers_by_group('odds_api')
        print_success(f"odds_api group has {len(odds_scrapers)} scrapers")
        print_info(f"  Scrapers: {odds_scrapers}")
        
        print_success("\n✅ All registry tests passed!")
        return True
        
    except Exception as e:
        print_error(f"Registry test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config() -> bool:
    """Test configuration loading."""
    print_header("TEST 2: Configuration Loading")
    
    try:
        from orchestration.config_loader import WorkflowConfig
        
        # Test 1: Load config
        print("Test 2.1: Loading config file...")
        config = WorkflowConfig()
        print_success("Config loaded successfully")
        
        # Test 2: Get enabled workflows
        print("\nTest 2.2: Getting enabled workflows...")
        enabled = config.get_enabled_workflows()
        print_success(f"Found {len(enabled)} enabled workflows:")
        for workflow_name in enabled:
            print_info(f"  • {workflow_name}")
        
        # Test 3: Get workflow details (FIXED METHOD NAME)
        if enabled:
            print("\nTest 2.3: Getting workflow details...")
            workflow_name = enabled[0]
            workflow = config.get_workflow_config(workflow_name)  # FIXED: was get_workflow()
            print_success(f"Got details for {workflow_name}:")
            print_info(f"  Description: {workflow.get('description', 'N/A')}")
            print_info(f"  Enabled: {workflow.get('enabled', False)}")
            
            # Test 4: Get scrapers for workflow
            print("\nTest 2.4: Getting scrapers for workflow...")
            scrapers = workflow.get('scrapers', [])  # Get from config dict
            print_success(f"Workflow has {len(scrapers)} scrapers:")
            for scraper in scrapers:
                print_info(f"  • {scraper['name']} (order: {scraper['order']})")
        
        # Test 5: Get settings
        print("\nTest 2.5: Getting settings...")
        settings = config.get_settings()
        print_success(f"Settings loaded:")
        print_info(f"  Timezone: {settings.get('timezone', 'N/A')}")
        print_info(f"  Max concurrent: {settings.get('max_concurrent_workflows', 'N/A')}")
        
        print_success("\n✅ All config tests passed!")
        return True
        
    except Exception as e:
        print_error(f"Config test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_controller() -> bool:
    """Test master controller."""
    print_header("TEST 3: Master Controller")
    
    try:
        from orchestration.master_controller import MasterWorkflowController
        from datetime import datetime
        import pytz
        
        # Test 1: Initialize controller
        print("Test 3.1: Initializing controller...")
        controller = MasterWorkflowController()
        print_success("Controller initialized")
        
        # Test 2: Evaluate workflows
        print("\nTest 3.2: Evaluating all workflows...")
        ET = pytz.timezone('America/New_York')
        current_time = datetime.now(ET)
        
        print_info(f"Evaluation time: {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        decisions = controller.evaluate_all_workflows(current_time)
        print_success(f"Evaluated {len(decisions)} workflows:")
        
        for decision in decisions:
            icon = "🟢 RUN" if decision.action.value == "RUN" else "⏭️  SKIP"
            print_info(f"\n  {icon} {decision.workflow_name}")
            print_info(f"    Reason: {decision.reason}")
            if decision.scrapers:  # FIXED: was scrapers_to_run
                print_info(f"    Scrapers: {len(decision.scrapers)}")
        
        print_success("\n✅ All controller tests passed!")
        return True
        
    except Exception as e:
        print_error(f"Controller test failed: {e}")
        print_info("\nNote: Controller tests may fail if:")
        print_info("  - BigQuery tables don't exist")
        print_info("  - NBAScheduleService isn't accessible")
        print_info("  - Network connectivity issues")
        import traceback
        traceback.print_exc()
        return False


def test_schedule_service() -> bool:
    """Test NBA Schedule Service integration."""
    print_header("TEST 4: NBA Schedule Service")
    
    try:
        from shared.utils.schedule import NBAScheduleService
        from datetime import date, timedelta
        
        # Test 1: Initialize service
        print("Test 4.1: Initializing schedule service...")
        schedule = NBAScheduleService()
        print_success("Schedule service initialized")
        
        # Test 2: Check games for a known date (yesterday)
        print("\nTest 4.2: Checking for recent games...")
        yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        has_games = schedule.has_games_on_date(yesterday)
        if has_games:
            count = schedule.get_game_count(yesterday)
            print_success(f"Found {count} games on {yesterday}")
            
            # Get game details
            games = schedule.get_games_for_date(yesterday)
            print_info(f"Sample game: {games[0].matchup if games else 'N/A'}")
        else:
            print_info(f"No games found on {yesterday} (might be off-season)")
        
        # Test 3: Check today
        print("\nTest 4.3: Checking today's schedule...")
        today = date.today().strftime('%Y-%m-%d')
        
        has_games_today = schedule.has_games_on_date(today)
        if has_games_today:
            count_today = schedule.get_game_count(today)
            print_success(f"✓ {count_today} games scheduled for today")
        else:
            print_info("No games scheduled for today")
        
        print_success("\n✅ All schedule service tests passed!")
        return True
        
    except Exception as e:
        print_error(f"Schedule service test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_bigquery_connection() -> bool:
    """Test BigQuery connectivity and tables."""
    print_header("TEST 5: BigQuery Connection")
    
    try:
        from google.cloud import bigquery
        
        # Test 1: Initialize client
        print("Test 5.1: Initializing BigQuery client...")
        client = bigquery.Client()
        print_success("BigQuery client initialized")
        
        # Test 2: Check if orchestration dataset exists
        print("\nTest 5.2: Checking nba_orchestration dataset...")
        dataset_id = "nba-props-platform.nba_orchestration"
        
        try:
            dataset = client.get_dataset(dataset_id)
            print_success(f"Dataset exists: {dataset_id}")
            
            # Test 3: List tables in dataset
            print("\nTest 5.3: Listing tables in dataset...")
            tables = list(client.list_tables(dataset))
            print_success(f"Found {len(tables)} tables:")
            
            expected_tables = [
                'scraper_execution_log',
                'workflow_decisions',
                'daily_expected_schedule',
                'cleanup_operations'
            ]
            
            for table_name in expected_tables:
                table_exists = any(t.table_id == table_name for t in tables)
                if table_exists:
                    print_success(f"  ✓ {table_name}")
                else:
                    print_error(f"  ✗ {table_name} (missing)")
            
        except Exception as e:
            print_error(f"Dataset check failed: {e}")
            print_info("\nDataset may not exist yet. Create with:")
            print_info("  bq mk nba-props-platform:nba_orchestration")
            return False
        
        print_success("\n✅ All BigQuery tests passed!")
        return True
        
    except Exception as e:
        print_error(f"BigQuery test failed: {e}")
        print_info("\nMake sure:")
        print_info("  1. GOOGLE_APPLICATION_CREDENTIALS is set")
        print_info("  2. Service account has BigQuery permissions")
        print_info("  3. nba_orchestration dataset exists")
        return False


def run_all_tests() -> Dict[str, bool]:
    """Run all integration tests."""
    results = {}
    
    print(f"\n{Colors.BOLD}🚀 Starting Phase 1 Orchestration Integration Tests{Colors.END}")
    print(f"{Colors.BOLD}Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    
    # Run tests in order
    results['registry'] = test_registry()
    results['config'] = test_config()
    results['schedule'] = test_schedule_service()
    results['bigquery'] = test_bigquery_connection()
    results['controller'] = test_controller()
    
    return results


def print_summary(results: Dict[str, bool]):
    """Print test summary."""
    print_header("TEST SUMMARY")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    
    for test_name, passed_flag in results.items():
        status = "✅ PASSED" if passed_flag else "❌ FAILED"
        color = Colors.GREEN if passed_flag else Colors.RED
        print(f"{color}{status}{Colors.END} - {test_name}")
    
    print(f"\n{Colors.BOLD}Results: {passed}/{total} tests passed{Colors.END}")
    
    if passed == total:
        print(f"{Colors.GREEN}{Colors.BOLD}🎉 All tests passed! System ready for deployment.{Colors.END}")
        return True
    else:
        print(f"{Colors.RED}{Colors.BOLD}⚠️  {failed} test(s) failed. Review errors above.{Colors.END}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Test Phase 1 Orchestration locally")
    parser.add_argument(
        '--test',
        choices=['registry', 'config', 'controller', 'schedule', 'bigquery', 'all'],
        default='all',
        help='Which test to run (default: all)'
    )
    
    args = parser.parse_args()
    
    if args.test == 'all':
        results = run_all_tests()
        success = print_summary(results)
        sys.exit(0 if success else 1)
    else:
        # Run single test
        test_func = {
            'registry': test_registry,
            'config': test_config,
            'controller': test_controller,
            'schedule': test_schedule_service,
            'bigquery': test_bigquery_connection
        }[args.test]
        
        success = test_func()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()