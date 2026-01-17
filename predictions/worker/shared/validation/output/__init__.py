"""
Validation Output Formatters

Formats validation results for different outputs:
- Terminal: Human-readable colored output
- JSON: Machine-readable structured output
"""

from shared.validation.output.terminal import (
    format_validation_result,
    print_validation_result,
    ValidationReport,
)
from shared.validation.output.json_output import (
    format_validation_json,
    print_validation_json,
)

__all__ = [
    'format_validation_result',
    'print_validation_result',
    'ValidationReport',
    'format_validation_json',
    'print_validation_json',
]
