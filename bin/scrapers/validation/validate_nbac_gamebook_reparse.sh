#!/bin/bash
# FILE: bin/validation/validate_nbac_gamebook_reparse.sh
#
# Validate NBA Gamebook Reparse job data quality and completeness
# Based on existing validation patterns

set -e

BUCKET="nba-scraped-data"
PDF_PREFIX="nba-com/gamebooks-pdf"
JSON_PREFIX="nba-com/gamebooks-data"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 [recent|full|compare] [days|limit]"
    echo ""
    echo "Commands:"
    echo "  recent [days]     Validate recent reparse data (default: 7 days)"
    echo "  full [limit]      Validate all reparse data (optional limit)"
    echo "  compare           Compare PDF vs JSON counts by season"
    echo ""
    echo "Examples:"
    echo "  $0 recent 3       # Validate last 3 days of reparse"
    echo "  $0 full 100       # Validate first 100 games"
    echo "  $0 compare        # Compare PDF/JSON counts"
    exit 1
}

log_info() {
    echo -e "${GREEN}ℹ️  $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

validate_recent() {
    local days=${1:-7}
    
    echo -e "${BLUE}🔍 Validating Recent Reparse Data (${days} days)${NC}"
    echo "================================================"
    
    # Get recent JSON files
    local cutoff_date=$(date -d "${days} days ago" +%Y-%m-%d)
    log_info "Checking JSON files created after: $cutoff_date"
    
    # Count recent JSON files
    local json_count=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/**/*.json" | \
        grep -E '/[0-9]{4}-[0-9]{2}-[0-9]{2}/' | \
        awk -F'/' '{print $(NF-1)}' | \
        awk -v cutoff="$cutoff_date" '$0 > cutoff' | \
        wc -l)
    
    log_info "Found $json_count recent JSON files"
    
    if [[ $json_count -eq 0 ]]; then
        log_warning "No recent JSON files found - reparse may not be working"
        return 1
    fi
    
    # Sample validation of recent files
    log_info "Sampling recent JSON files for validation..."
    
    local sample_files=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/**/*.json" | \
        grep -E '/[0-9]{4}-[0-9]{2}-[0-9]{2}/' | \
        awk -F'/' '{print $(NF-1)}' | \
        awk -v cutoff="$cutoff_date" '$0 > cutoff' | \
        head -10)
    
    local valid_count=0
    local total_sampled=0
    
    for date_dir in $sample_files; do
        local json_files=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/$date_dir/" 2>/dev/null | head -3)
        
        for json_file in $json_files; do
            if [[ -n "$json_file" ]]; then
                total_sampled=$((total_sampled + 1))
                if validate_single_json "$json_file"; then
                    valid_count=$((valid_count + 1))
                fi
            fi
        done
    done
    
    if [[ $total_sampled -eq 0 ]]; then
        log_warning "No JSON files could be sampled for validation"
        return 1
    fi
    
    local success_rate=$((valid_count * 100 / total_sampled))
    
    if [[ $success_rate -ge 90 ]]; then
        log_success "Validation passed: $valid_count/$total_sampled files valid (${success_rate}%)"
    elif [[ $success_rate -ge 70 ]]; then
        log_warning "Validation warning: $valid_count/$total_sampled files valid (${success_rate}%)"
    else
        log_error "Validation failed: $valid_count/$total_sampled files valid (${success_rate}%)"
        return 1
    fi
}

validate_single_json() {
    local json_file="$1"
    local temp_file="/tmp/validate_json_$$.json"
    
    # Download and check JSON structure
    if gcloud storage cp "$json_file" "$temp_file" 2>/dev/null; then
        # Check if it's valid JSON
        if ! jq empty "$temp_file" 2>/dev/null; then
            log_error "Invalid JSON format: $json_file"
            rm -f "$temp_file"
            return 1
        fi
        
        # Check for required fields
        local game_code=$(jq -r '.game_code // empty' "$temp_file")
        local active_count=$(jq -r '.active_count // 0' "$temp_file")
        local total_players=$(jq -r '.total_players // 0' "$temp_file")
        local pdf_source=$(jq -r '.pdf_source // empty' "$temp_file")
        
        rm -f "$temp_file"
        
        # Validate data
        if [[ -z "$game_code" ]]; then
            log_error "Missing game_code in: $json_file"
            return 1
        fi
        
        if [[ "$pdf_source" != "gcs" ]]; then
            log_error "Expected pdf_source='gcs', got '$pdf_source' in: $json_file"
            return 1
        fi
        
        if [[ $active_count -eq 0 && $total_players -eq 0 ]]; then
            log_error "No players found in: $json_file"
            return 1
        fi
        
        return 0
    else
        log_error "Could not download: $json_file"
        return 1
    fi
}

validate_full() {
    local limit=${1:-""}
    
    echo -e "${BLUE}🔍 Full Reparse Data Validation${NC}"
    echo "================================"
    
    log_info "Scanning all JSON files..."
    
    local json_files
    if [[ -n "$limit" ]]; then
        json_files=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/**/*.json" | head -"$limit")
        log_info "Limiting validation to first $limit files"
    else
        json_files=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/**/*.json")
    fi
    
    local total_files=$(echo "$json_files" | wc -l)
    log_info "Found $total_files JSON files to validate"
    
    local valid_count=0
    local current=0
    
    for json_file in $json_files; do
        current=$((current + 1))
        
        if [[ $((current % 100)) -eq 0 ]]; then
            log_info "Progress: $current/$total_files files processed"
        fi
        
        if validate_single_json "$json_file"; then
            valid_count=$((valid_count + 1))
        fi
    done
    
    local success_rate=$((valid_count * 100 / total_files))
    
    echo ""
    log_info "Validation Summary:"
    log_info "  Total files: $total_files"
    log_info "  Valid files: $valid_count"
    log_info "  Success rate: ${success_rate}%"
    
    if [[ $success_rate -ge 95 ]]; then
        log_success "Full validation passed with ${success_rate}% success rate"
    elif [[ $success_rate -ge 85 ]]; then
        log_warning "Full validation completed with ${success_rate}% success rate"
    else
        log_error "Full validation failed with ${success_rate}% success rate"
        return 1
    fi
}

compare_pdf_json() {
    echo -e "${BLUE}🔍 PDF vs JSON Comparison${NC}"
    echo "========================="
    
    log_info "Counting PDFs by season..."
    
    # Count PDFs by season (based on directory structure)
    local pdf_2021=$(gcloud storage ls "gs://$BUCKET/$PDF_PREFIX/2021-*/**/*.pdf" 2>/dev/null | wc -l)
    local pdf_2022=$(gcloud storage ls "gs://$BUCKET/$PDF_PREFIX/2022-*/**/*.pdf" 2>/dev/null | wc -l)  
    local pdf_2023=$(gcloud storage ls "gs://$BUCKET/$PDF_PREFIX/2023-*/**/*.pdf" 2>/dev/null | wc -l)
    local pdf_2024=$(gcloud storage ls "gs://$BUCKET/$PDF_PREFIX/2024-*/**/*.pdf" 2>/dev/null | wc -l)
    
    log_info "Counting JSONs by season..."
    
    # Count JSONs by season
    local json_2021=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/2021-*/**/*.json" 2>/dev/null | wc -l)
    local json_2022=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/2022-*/**/*.json" 2>/dev/null | wc -l)
    local json_2023=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/2023-*/**/*.json" 2>/dev/null | wc -l)
    local json_2024=$(gcloud storage ls "gs://$BUCKET/$JSON_PREFIX/2024-*/**/*.json" 2>/dev/null | wc -l)
    
    echo ""
    echo "Season Comparison:"
    echo "=================="
    printf "%-10s %8s %8s %10s\n" "Season" "PDFs" "JSONs" "Conversion"
    echo "----------------------------------------"
    
    compare_season "2021-22" $pdf_2021 $json_2021
    compare_season "2022-23" $pdf_2022 $json_2022  
    compare_season "2023-24" $pdf_2023 $json_2023
    compare_season "2024-25" $pdf_2024 $json_2024
    
    local total_pdfs=$((pdf_2021 + pdf_2022 + pdf_2023 + pdf_2024))
    local total_jsons=$((json_2021 + json_2022 + json_2023 + json_2024))
    
    echo "----------------------------------------"
    compare_season "TOTAL" $total_pdfs $total_jsons
}

compare_season() {
    local season="$1"
    local pdf_count="$2" 
    local json_count="$3"
    
    if [[ $pdf_count -eq 0 ]]; then
        printf "%-10s %8s %8s %10s\n" "$season" "$pdf_count" "$json_count" "N/A"
    else
        local conversion_rate=$((json_count * 100 / pdf_count))
        printf "%-10s %8s %8s %9s%%\n" "$season" "$pdf_count" "$json_count" "$conversion_rate"
        
        if [[ $conversion_rate -lt 50 ]]; then
            log_error "Low conversion rate for $season: ${conversion_rate}%"
        elif [[ $conversion_rate -lt 80 ]]; then
            log_warning "Moderate conversion rate for $season: ${conversion_rate}%"
        fi
    fi
}

# Main command processing
case "${1:-recent}" in
    recent)
        validate_recent "$2"
        ;;
    full)
        validate_full "$2"
        ;;
    compare)
        compare_pdf_json
        ;;
    *)
        usage
        ;;
esac