#!/bin/bash
# SAVE TO: ~/code/nba-stats-scraper/bin/scheduling/pause_all_schedulers.sh

PROJECT_ID="nba-props-platform"
REGION="us-west2"

echo "⏸️ NBA Individual Scheduler Transition Manager"
echo "=============================================="
echo "This script helps you safely transition from individual schedulers to workflows"
echo ""

# List of individual schedulers (not workflow triggers)
INDIVIDUAL_SCHEDULERS=(
    "nba-odds-events"
    "nba-odds-props" 
    "nba-odds-team-players"
    "nba-player-list"
    "nba-injury-report"
    "nba-bdl-active-players"
    "nba-espn-scoreboard"
    "nba-nbacom-scoreboard"
    "nba-bdl-boxscores"
    "nba-espn-boxscore"
    "nba-bdl-player-boxscores"
    "nba-bdl-active-players"
    "nba-player-movement"
    "nba-season-schedule"
    "nba-team-roster"
    "nba-espn-gsw-roster"
    "nba-nbacom-playbyplay"
    "nba-nbacom-player-boxscore"
)

show_current_status() {
    echo "📊 Current Scheduler Status"
    echo "=========================="
    
    echo ""
    echo "🔄 Workflow Schedulers (New System):"
    gcloud scheduler jobs list --location=$REGION --filter="name ~ .*trigger" --format="table(name,schedule,state)" 2>/dev/null
    
    echo ""
    echo "🗓️ Individual Schedulers (Old System):"
    gcloud scheduler jobs list --location=$REGION --filter="NOT name ~ .*trigger" --format="table(name,schedule,state)" 2>/dev/null
}

pause_individual_schedulers() {
    echo ""
    echo "⏸️ Pausing Individual Schedulers"
    echo "================================"
    echo "This will pause (not delete) all individual schedulers."
    echo "You can always resume them if needed."
    echo ""
    
    # Show what will be paused
    echo "📋 Schedulers that will be paused:"
    for scheduler in "${INDIVIDUAL_SCHEDULERS[@]}"; do
        if gcloud scheduler jobs describe $scheduler --location=$REGION >/dev/null 2>&1; then
            echo "  ✅ $scheduler (exists)"
        else
            echo "  ⚠️ $scheduler (not found - skipping)"
        fi
    done
    
    echo ""
    read -p "Are you sure you want to pause these individual schedulers? (y/N): " confirm
    
    if [[ $confirm =~ ^[Yy]$ ]]; then
        echo ""
        echo "⏸️ Pausing schedulers..."
        
        paused_count=0
        for scheduler in "${INDIVIDUAL_SCHEDULERS[@]}"; do
            if gcloud scheduler jobs describe $scheduler --location=$REGION >/dev/null 2>&1; then
                echo "  Pausing $scheduler..."
                if gcloud scheduler jobs pause $scheduler --location=$REGION --quiet 2>/dev/null; then
                    echo "    ✅ Paused"
                    paused_count=$((paused_count + 1))
                else
                    echo "    ❌ Failed to pause"
                fi
            fi
        done
        
        echo ""
        echo "✅ Paused $paused_count individual schedulers"
        echo "🔄 Workflow schedulers continue running"
        
    else
        echo "❌ Pausing cancelled"
    fi
}

resume_individual_schedulers() {
    echo ""
    echo "▶️ Resuming Individual Schedulers"
    echo "================================="
    echo "This will resume all paused individual schedulers."
    echo ""
    
    read -p "Are you sure you want to resume individual schedulers? (y/N): " confirm
    
    if [[ $confirm =~ ^[Yy]$ ]]; then
        echo ""
        echo "▶️ Resuming schedulers..."
        
        resumed_count=0
        for scheduler in "${INDIVIDUAL_SCHEDULERS[@]}"; do
            if gcloud scheduler jobs describe $scheduler --location=$REGION >/dev/null 2>&1; then
                state=$(gcloud scheduler jobs describe $scheduler --location=$REGION --format="value(state)")
                if [[ "$state" == "PAUSED" ]]; then
                    echo "  Resuming $scheduler..."
                    if gcloud scheduler jobs resume $scheduler --location=$REGION --quiet 2>/dev/null; then
                        echo "    ✅ Resumed"
                        resumed_count=$((resumed_count + 1))
                    else
                        echo "    ❌ Failed to resume"
                    fi
                fi
            fi
        done
        
        echo ""
        echo "✅ Resumed $resumed_count individual schedulers"
        
    else
        echo "❌ Resuming cancelled"
    fi
}

delete_individual_schedulers() {
    echo ""
    echo "🗑️ DELETE Individual Schedulers (PERMANENT)"
    echo "=========================================="
    echo "⚠️ WARNING: This will PERMANENTLY DELETE all individual schedulers!"
    echo "Only do this after workflows have been running successfully for at least 1 week."
    echo ""
    
    echo "📋 Schedulers that will be DELETED:"
    for scheduler in "${INDIVIDUAL_SCHEDULERS[@]}"; do
        if gcloud scheduler jobs describe $scheduler --location=$REGION >/dev/null 2>&1; then
            echo "  • $scheduler"
        fi
    done
    
    echo ""
    echo "⚠️ This action cannot be undone!"
    read -p "Type 'DELETE' to confirm permanent deletion: " confirm
    
    if [[ $confirm == "DELETE" ]]; then
        echo ""
        echo "🗑️ Deleting schedulers..."
        
        deleted_count=0
        for scheduler in "${INDIVIDUAL_SCHEDULERS[@]}"; do
            if gcloud scheduler jobs describe $scheduler --location=$REGION >/dev/null 2>&1; then
                echo "  Deleting $scheduler..."
                if gcloud scheduler jobs delete $scheduler --location=$REGION --quiet 2>/dev/null; then
                    echo "    ✅ Deleted"
                    deleted_count=$((deleted_count + 1))
                else
                    echo "    ❌ Failed to delete"
                fi
            fi
        done
        
        echo ""
        echo "✅ Deleted $deleted_count individual schedulers"
        echo "🔄 Only workflow schedulers remain"
        
    else
        echo "❌ Deletion cancelled"
    fi
}

# Main menu
show_menu() {
    echo ""
    echo "🎯 What would you like to do?"
    echo "1. Show current status"
    echo "2. Pause individual schedulers (recommended first step)"
    echo "3. Resume individual schedulers (if needed)"
    echo "4. Delete individual schedulers (PERMANENT - only when confident)"
    echo "5. Exit"
    echo ""
}

# Main loop
while true; do
    show_menu
    read -p "Enter your choice (1-5): " choice
    
    case $choice in
        1)
            show_current_status
            ;;
        2)
            pause_individual_schedulers
            ;;
        3)
            resume_individual_schedulers
            ;;
        4)
            delete_individual_schedulers
            ;;
        5)
            echo ""
            echo "👋 Transition complete!"
            echo ""
            echo "🔍 Monitor your workflows:"
            echo "gcloud workflows executions list real-time-business --location=$REGION"
            exit 0
            ;;
        *)
            echo "❌ Invalid choice. Please enter 1-5."
            ;;
    esac
    
    echo ""
    echo "Press Enter to continue..."
    read
done
