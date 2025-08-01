#!/bin/bash
# File Organization Cleanup Script
# SAVE TO: ~/code/nba-stats-scraper/bin/utilities/cleanup_bin_directory.sh

echo "🧹 NBA Project File Cleanup Recommendations"
echo "==========================================="

echo ""
echo "📋 FILES TO CONSIDER MOVING TO ARCHIVE:"
echo "========================================"

echo ""
echo "🗂️ bin/deployment/ - Potentially outdated:"
echo "  • deploy_real_time_business.sh    → bin/archive/ (replaced by deploy_workflows.sh)"
echo "  • fix_workflow_permissions.sh     → bin/archive/ (one-time setup, completed)"

echo ""
echo "🗂️ bin/monitoring/ - Cleanup needed:"
echo "  • check_deployment.sh.backup      → DELETE (backup file)"
echo "  • deployment_status.sh.backup     → DELETE (backup file)"
echo "  • scheduler_bulletproof.sh         → bin/archive/ (replaced by monitor_workflows.sh)"
echo "  • scheduler_comprehensive.sh       → bin/archive/ (replaced by monitor_workflows.sh)"
echo "  • scheduler_inventory.sh           → bin/archive/ (replaced by monitor_workflows.sh)"

echo ""
echo "🗂️ bin/scheduling/ - Consider renaming:"
echo "  • setup_all_schedulers.sh          → bin/archive/ (old individual scheduler setup)"
echo "  • resume_schedulers.sh             → rename to 'resume_individual_schedulers.sh' (clearer)"

echo ""
echo "🗂️ bin/testing/ - Potentially outdated:"
echo "  • test_scrapers.sh.backup          → DELETE (backup file)"
echo "  • test_workflow.sh                 → CHECK if still relevant (might be outdated)"

echo ""
echo "📝 RECOMMENDED ACTIONS:"
echo "======================"
echo ""
echo "1. Move outdated deployment scripts:"
echo "   mv bin/deployment/deploy_real_time_business.sh bin/archive/"
echo "   mv bin/deployment/fix_workflow_permissions.sh bin/archive/"
echo ""
echo "2. Clean up monitoring backups:"
echo "   rm bin/monitoring/*.backup"
echo ""
echo "3. Archive old scheduler monitoring:"
echo "   mv bin/monitoring/scheduler_*.sh bin/archive/"
echo ""
echo "4. Clean up testing backups:"
echo "   rm bin/testing/*.backup"
echo ""
echo "5. Rename for clarity:"
echo "   mv bin/scheduling/resume_schedulers.sh bin/scheduling/resume_individual_schedulers.sh"
echo ""
echo "6. Archive old scheduler setup:"
echo "   mv bin/scheduling/setup_all_schedulers.sh bin/archive/"

echo ""
echo "💡 TIP: Review each file before moving to ensure it's not still needed!"
