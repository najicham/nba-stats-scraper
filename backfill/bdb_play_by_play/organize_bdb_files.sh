#!/bin/bash
# bin/backfill/organize_bdb_files.sh
# Big Data Ball File Organizer for NBA Backfill
# Extracts zip files and organizes into GCS-ready structure

set -e  # Exit on any error

# Configuration
BASE_DIR="/Users/naji/Documents/BigDataBall"
ORGANIZED_DIR="${BASE_DIR}/organized"
ZIP_FILES=(
    "${BASE_DIR}/2021-2022_NBA_PbP_Logs.zip"
    "${BASE_DIR}/2022-2023_NBA_PbP_Logs.zip" 
    "${BASE_DIR}/2023-2024_NBA_PbP_Logs.zip"
)

# Function to map season names (instead of associative array)
map_season_name() {
    case "$1" in
        "2021-2022") echo "2021-22" ;;
        "2022-2023") echo "2022-23" ;;
        "2023-2024") echo "2023-24" ;;
        *) echo "" ;;
    esac
}

echo "🏀 Big Data Ball File Organizer"
echo "==============================="
echo "Base Directory: ${BASE_DIR}"
echo "Organized Output: ${ORGANIZED_DIR}"
echo ""

# Create organized directory
echo "📁 Creating organized directory structure..."
mkdir -p "${ORGANIZED_DIR}"

# Function to extract game info from filename
extract_game_info() {
    local filename="$1"
    
    # Extract date: [2021-10-19]-0022100001-BKN@MIL.csv
    local date=$(echo "$filename" | grep -o '\[.*\]' | tr -d '[]')
    
    # Extract game_id: 0022100001
    local game_id=$(echo "$filename" | grep -o '00[0-9]\{8\}')
    
    echo "${date}|${game_id}"
}

# Function to organize files from a zip
organize_zip() {
    local zip_file="$1"
    local season_name="$2"
    local season_dir="$3"
    
    echo ""
    echo "📦 Processing: $(basename "$zip_file")"
    echo "   Season: $season_name → $season_dir"
    
    # Create temporary extraction directory
    temp_dir="${BASE_DIR}/temp_${season_name}"
    mkdir -p "$temp_dir"
    
    # Extract zip file
    echo "   Extracting zip file..."
    unzip -q "$zip_file" -d "$temp_dir"
    
    # Find CSV files (they might be in subdirectories)
    csv_files=$(find "$temp_dir" -name "*.csv" -type f)
    file_count=0
    processed_count=0
    
    echo "   Found CSV files, organizing..."
    
    while IFS= read -r csv_file; do
        if [[ -n "$csv_file" ]]; then
            file_count=$((file_count + 1))
            
            filename=$(basename "$csv_file")
            
            # Skip combined stats files
            if [[ "$filename" == *"combined-stats"* ]]; then
                echo "   Skipping season summary: $filename"
                continue
            fi
            
            # Extract game info
            game_info=$(extract_game_info "$filename")
            date=$(echo "$game_info" | cut -d'|' -f1)
            game_id=$(echo "$game_info" | cut -d'|' -f2)
            
            if [[ -n "$date" && -n "$game_id" ]]; then
                # Create target directory structure
                target_dir="${ORGANIZED_DIR}/${season_dir}/${date}/game_${game_id}"
                mkdir -p "$target_dir"
                
                # Copy file to target location
                cp "$csv_file" "$target_dir/"
                processed_count=$((processed_count + 1))
                
                if [[ $((processed_count % 50)) -eq 0 ]]; then
                    echo "   Processed $processed_count files..."
                fi
            else
                echo "   ⚠️  Could not parse: $filename"
            fi
        fi
    done <<< "$csv_files"
    
    echo "   ✅ Organized $processed_count of $file_count files"
    
    # Clean up temporary directory
    rm -rf "$temp_dir"
}

# Process each zip file
total_files=0
for zip_file in "${ZIP_FILES[@]}"; do
    if [[ -f "$zip_file" ]]; then
        # Extract season name from zip filename
        zip_basename=$(basename "$zip_file" .zip)
        season_name=$(echo "$zip_basename" | sed 's/_NBA_PbP_Logs//')
        season_dir=$(map_season_name "$season_name")
        
        if [[ -n "$season_dir" ]]; then
            organize_zip "$zip_file" "$season_name" "$season_dir"
        else
            echo "❌ Unknown season format: $season_name"
        fi
    else
        echo "❌ Zip file not found: $zip_file"
    fi
done

echo ""
echo "📊 Organization Summary:"
echo "======================="

# Count files in each season
for season in "2021-22" "2022-23" "2023-24"; do
    if [[ -d "${ORGANIZED_DIR}/${season}" ]]; then
        count=$(find "${ORGANIZED_DIR}/${season}" -name "*.csv" | wc -l)
        dates=$(find "${ORGANIZED_DIR}/${season}" -type d -name "20*" | wc -l)
        echo "   $season: $count games across $dates dates"
        total_files=$((total_files + count))
    fi
done

echo ""
echo "   Total files organized: $total_files"
echo ""

# Generate GCS upload commands
echo "🚀 GCS Upload Commands:"
echo "======================="
echo ""
echo "# Upload all organized files to GCS"
echo "gsutil -m cp -r \"${ORGANIZED_DIR}/*\" gs://nba-scraped-data/big-data-ball/"
echo ""
echo "# Verify upload"
echo "gsutil ls -l gs://nba-scraped-data/big-data-ball/"
echo ""

# Generate individual season upload commands
for season in "2021-22" "2022-23" "2023-24"; do
    if [[ -d "${ORGANIZED_DIR}/${season}" ]]; then
        echo "# Upload $season only"
        echo "gsutil -m cp -r \"${ORGANIZED_DIR}/${season}\" gs://nba-scraped-data/big-data-ball/"
    fi
done

echo ""
echo "📁 Organized files ready for upload!"
echo "   Location: ${ORGANIZED_DIR}"
echo ""
echo "Next steps:"
echo "1. Review organized structure: ls -la \"${ORGANIZED_DIR}\""
echo "2. Run GCS upload command above"
echo "3. Verify files in GCS bucket"