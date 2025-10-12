#!/bin/bash
# Helper script to create new requirements file

if [ -z "$1" ]; then
  echo "Usage: ./new_requirements.sh [processor_name]"
  echo "Example: ./new_requirements.sh odds_game_lines"
  exit 1
fi

PROCESSOR_NAME="$1"
OUTPUT_FILE="in_progress/${PROCESSOR_NAME}_requirements.md"

if [ -f "$OUTPUT_FILE" ]; then
  echo "❌ Error: $OUTPUT_FILE already exists"
  exit 1
fi

echo "📋 Creating requirements file for: $PROCESSOR_NAME"
cp ../VALIDATOR_REQUIREMENTS_TEMPLATE.md "$OUTPUT_FILE"

# Replace processor name in file
sed -i "s/\[FILL IN: e.g., odds_api_game_lines\]/$PROCESSOR_NAME/g" "$OUTPUT_FILE"

echo "✅ Created: $OUTPUT_FILE"
echo ""
echo "Next steps:"
echo "  1. Edit file: nano $OUTPUT_FILE"
echo "  2. Fill out template (see ../HOW_TO_USE_VALIDATOR_TEMPLATE.md)"
echo "  3. Share with validation team when complete"
