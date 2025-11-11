"""
orchestration/workflow_executor.py

Workflow Executor - Runs scrapers with dependency management

Handles:
- Sequential execution (e.g., events before props)
- Parallel execution (e.g., multiple box score scrapers)
- Error handling and logging
"""

import logging
from typing import List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from scrapers.registry import get_scraper_instance
from shared.utils.bigquery_utils import insert_bigquery_rows

logger = logging.getLogger(__name__)


class WorkflowExecutor:
    """
    Executes workflows with proper dependency management.
    
    Handles:
    - Sequential execution (e.g., events before props)
    - Parallel execution (e.g., multiple box score scrapers)
    - Error handling and logging
    """
    
    def execute(
        self,
        workflow_name: str,
        scrapers: List[str],
        target_games: List[str] = None
    ) -> Dict[str, Any]:
        """
        Execute workflow with given scrapers.
        
        Args:
            workflow_name: Workflow identifier
            scrapers: List of scraper names to execute
            target_games: Optional list of game IDs to process
        
        Returns:
            Dict with execution summary
        """
        start_time = datetime.utcnow()
        
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"▶️  Executing Workflow: {workflow_name}")
        logger.info(f"   Scrapers: {len(scrapers)}")
        if target_games:
            logger.info(f"   Target Games: {len(target_games)}")
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        results = []
        
        # Simple parallel execution for now
        # TODO: Add dependency-aware execution for multi-step workflows
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            
            for scraper_name in scrapers:
                opts = {
                    'workflow': workflow_name,
                    'source': 'CONTROLLER'
                }
                if target_games:
                    opts['target_games'] = target_games
                
                future = executor.submit(self._run_scraper, scraper_name, opts)
                futures[future] = scraper_name
            
            for future in as_completed(futures):
                scraper_name = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result['status'] == 'success':
                        logger.info(f"✅ {scraper_name}: SUCCESS")
                    else:
                        logger.error(f"❌ {scraper_name}: FAILED")
                        
                except Exception as e:
                    logger.error(f"❌ {scraper_name}: EXCEPTION - {e}")
                    results.append({
                        'scraper_name': scraper_name,
                        'status': 'failed',
                        'error': str(e)
                    })
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        success_count = sum(1 for r in results if r['status'] == 'success')
        failed_count = len(results) - success_count
        
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(f"✅ Workflow Complete: {workflow_name}")
        logger.info(f"   Duration: {duration:.1f}s")
        logger.info(f"   Success: {success_count}/{len(scrapers)}")
        logger.info(f"   Failed: {failed_count}/{len(scrapers)}")
        logger.info(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        return {
            'workflow': workflow_name,
            'status': 'success' if failed_count == 0 else 'partial',
            'scrapers_executed': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'duration_seconds': duration,
            'results': results
        }
    
    def _run_scraper(self, scraper_name: str, opts: dict) -> Dict[str, Any]:
        """Run single scraper and return result."""
        start_time = datetime.utcnow()
        
        try:
            scraper = get_scraper_instance(scraper_name)
            result = scraper.run(opts=opts)
            
            return {
                'scraper_name': scraper_name,
                'status': 'success' if result else 'failed',
                'run_id': scraper.run_id if hasattr(scraper, 'run_id') else str(start_time.timestamp()),
                'duration': (datetime.utcnow() - start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Scraper {scraper_name} failed: {e}", exc_info=True)
            
            return {
                'scraper_name': scraper_name,
                'status': 'failed',
                'error': str(e),
                'duration': (datetime.utcnow() - start_time).total_seconds()
            }
