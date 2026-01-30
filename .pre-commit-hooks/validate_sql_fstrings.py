#!/usr/bin/env python3
"""
Pre-commit hook: Validate SQL f-strings have proper f prefix

Detects multi-line strings containing SQL keywords that have curly brace
variable patterns (like {self.project_id}, {table_name}) but are missing
the 'f' prefix, which means the variables won't be interpolated.

Examples caught:
    # BAD - missing f prefix, {self.project_id} won't be interpolated
    query = '''
        SELECT * FROM `{self.project_id}.dataset.table`
    '''

    # GOOD - has f prefix
    query = f'''
        SELECT * FROM `{self.project_id}.dataset.table`
    '''

    # OK - no variables to interpolate
    query = '''
        SELECT * FROM `my-project.dataset.table`
    '''

Exit codes:
- 0: No issues found
- 1: Found SQL strings with uninterpolated variables

Usage:
  python .pre-commit-hooks/validate_sql_fstrings.py [files...]
"""

import re
import sys
from pathlib import Path
from typing import List, Tuple, NamedTuple


class Issue(NamedTuple):
    """Represents a detected issue."""
    file: str
    line: int
    preview: str
    variable_patterns: List[str]
    in_docstring: bool = False


# SQL keywords that identify a string as likely being SQL
SQL_KEYWORDS = [
    r'\bSELECT\b',
    r'\bINSERT\b',
    r'\bUPDATE\b',
    r'\bDELETE\b',
    r'\bMERGE\b',
    r'\bFROM\b',
    r'\bJOIN\b',
    r'\bWHERE\b',
    r'\bCREATE\s+TABLE\b',
    r'\bALTER\s+TABLE\b',
    r'\bDROP\s+TABLE\b',
    r'\bTRUNCATE\b',
    r'\bGROUP\s+BY\b',
    r'\bORDER\s+BY\b',
]

# Pattern to match variable-like curly brace patterns that should be interpolated
# These are patterns that look like Python variables/expressions
VARIABLE_PATTERNS = [
    r'\{self\.\w+\}',           # {self.project_id}
    r'\{project[_\w]*\}',       # {project}, {project_id}
    r'\{table[_\w]*\}',         # {table}, {table_name}, {table_id}
    r'\{dataset[_\w]*\}',       # {dataset}, {dataset_id}
    r'\{schema[_\w]*\}',        # {schema}
    r'\{database[_\w]*\}',      # {database}
    r'\{query[_\w]*\}',         # {query}
    r'\{date[_\w]*\}',          # {date}, {game_date}
    r'\{player[_\w]*\}',        # {player_id}
    r'\{game[_\w]*\}',          # {game_id}
    r'\{batch[_\w]*\}',         # {batch_id}
    r'\{config[_\w]*\}',        # {config}
    r'\{client[_\w]*\}',        # {client}
    r'\{bucket[_\w]*\}',        # {bucket}
    r'\{region[_\w]*\}',        # {region}
    r'\{env[_\w]*\}',           # {env}
    r'\{prefix[_\w]*\}',        # {prefix}
    r'\{suffix[_\w]*\}',        # {suffix}
    r'\{name[_\w]*\}',          # {name}
    r'\{id[_\w]*\}',            # {id}
    r'\{column[_\w]*\}',        # {column}
    r'\{field[_\w]*\}',         # {field}
    r'\{value[_\w]*\}',         # {value}
    r'\{param[_\w]*\}',         # {param}
    r'\{start[_\w]*\}',         # {start_date}
    r'\{end[_\w]*\}',           # {end_date}
]

# File patterns to check
INCLUDE_PATTERNS = [
    "*.py",
]

# File patterns to exclude
EXCLUDE_PATTERNS = [
    "*test*.py",
    "*_test.py",
    "test_*.py",
    "conftest.py",
    "*migrations*",
    ".pre-commit-hooks/*",
]

# Directory patterns to exclude entirely
EXCLUDE_DIRS = [
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    ".tox",
    "build",
    "dist",
    "*.egg-info",
    ".backups",
]

# Comment markers that suppress warnings (for intentional non-f-strings)
SUPPRESS_MARKERS = [
    "# noqa: sql-fstring",
    "# sql-template",
    "# template-string",
]


def should_check_file(file_path: Path) -> bool:
    """Determine if a file should be checked."""
    # Check if file exists (handle broken symlinks)
    if not file_path.exists():
        return False

    # Check if any parent directory should be excluded
    path_str = str(file_path)
    for exclude_dir in EXCLUDE_DIRS:
        # Check for directory in path
        if f"/{exclude_dir}/" in path_str or path_str.startswith(f"{exclude_dir}/"):
            return False

    # Check if matches include patterns
    matches_include = any(
        file_path.match(pattern) for pattern in INCLUDE_PATTERNS
    )
    if not matches_include:
        return False

    # Check if matches exclude patterns
    matches_exclude = any(
        file_path.match(pattern) for pattern in EXCLUDE_PATTERNS
    )
    if matches_exclude:
        return False

    return True


def is_sql_string(content: str) -> bool:
    """Check if a string contains SQL keywords."""
    for keyword_pattern in SQL_KEYWORDS:
        if re.search(keyword_pattern, content, re.IGNORECASE):
            return True
    return False


def find_variable_patterns(content: str) -> List[str]:
    """Find all variable-like curly brace patterns in the string."""
    found = []
    for pattern in VARIABLE_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE)
        found.extend(matches)
    return found


def find_docstring_ranges(content: str) -> List[Tuple[int, int]]:
    """
    Find all docstring ranges in the content.

    Returns a list of (start, end) positions for each docstring.
    """
    ranges = []

    # Find all triple-quoted strings
    triple_quote_pattern = re.compile(
        r'''(\'\'\'|""").*?\1''',
        re.DOTALL
    )

    for match in triple_quote_pattern.finditer(content):
        start = match.start()
        end = match.end()

        # Check if this is a docstring by looking at what precedes it
        before = content[:start].rstrip()

        # A docstring appears after:
        # - A function/class definition line ending with ':'
        # - At the start of a module (nothing but whitespace/comments before)
        # - After another docstring (module docstring followed by code)

        lines_before = before.split('\n')
        last_line = lines_before[-1].strip() if lines_before else ''

        # Check if last non-empty line ends with ':'
        # (function def, class def, or start of block)
        is_after_def = last_line.endswith(':')

        # Check if this is at module start
        is_module_start = not before or all(
            line.strip() == '' or line.strip().startswith('#')
            for line in lines_before
        )

        if is_after_def or is_module_start:
            ranges.append((start, end))

    return ranges


def is_in_docstring(content: str, pos: int, docstring_ranges: List[Tuple[int, int]]) -> bool:
    """
    Check if a position in the content is inside a docstring.
    """
    for start, end in docstring_ranges:
        if start <= pos < end:
            return True
    return False


def has_suppress_marker(content: str, pos: int) -> bool:
    """Check if there's a suppress marker near this position."""
    # Look at the lines around this position
    line_start = content.rfind('\n', 0, pos) + 1
    line_end = content.find('\n', pos)
    if line_end == -1:
        line_end = len(content)

    # Check current line and previous few lines
    search_start = max(0, line_start - 200)
    search_text = content[search_start:line_end]

    for marker in SUPPRESS_MARKERS:
        if marker in search_text:
            return True
    return False


def is_format_string(content: str, match_end: int) -> bool:
    """
    Check if a string is followed by .format( call.

    This indicates intentional template usage, not a missing f-string prefix.
    Example: "SELECT * FROM {table}".format(table=name)
    """
    # Look at the content after the string (skip whitespace)
    after = content[match_end:match_end + 50].lstrip()

    # Check for .format( pattern
    if after.startswith('.format('):
        return True

    # Also check for % formatting (less common but valid)
    if after.startswith('% ') or after.startswith('%('):
        return True

    return False


def check_file(file_path: Path) -> List[Issue]:
    """
    Check a file for SQL strings with uninterpolated variables.

    Returns:
        List of Issue objects for each problematic string found.
    """
    issues = []

    try:
        content = file_path.read_text()
    except Exception as e:
        return [Issue(
            file=str(file_path),
            line=0,
            preview=f"Could not read file: {e}",
            variable_patterns=[],
            in_docstring=False
        )]

    # Pre-compute docstring ranges for efficient lookup
    docstring_ranges = find_docstring_ranges(content)

    # Pattern to find multi-line strings (triple-quoted)
    # We need to identify strings that are NOT f-strings
    #
    # Strategy:
    # 1. Find all triple-quoted strings with their positions
    # 2. Check if preceded by 'f' or 'F' (or rf, fr, etc.)
    # 3. If not an f-string, check for SQL keywords and variable patterns

    # Regex to match triple-quoted strings
    # This captures the quote style and content
    # Using numbered groups for reliable backreferences
    triple_quote_pattern = re.compile(
        r'''
        ([fFrRbBuU]{0,2})           # Group 1: Optional prefix (f, r, fr, rf, etc.)
        (\'\'\'|""")                # Group 2: Triple quotes
        (.*?)                        # Group 3: String content (non-greedy)
        \2                           # Matching closing quotes (backreference to group 2)
        ''',
        re.VERBOSE | re.DOTALL
    )

    # Also check for single-line strings that might contain SQL
    # Using numbered groups for reliable backreferences
    single_quote_pattern = re.compile(
        r'''
        ([fFrRbBuU]{0,2})           # Group 1: Optional prefix
        ('|")                        # Group 2: Single or double quote
        ([^'"\n]+?)                  # Group 3: String content (no newlines for single-line)
        \2                           # Matching closing quote (backreference to group 2)
        ''',
        re.VERBOSE
    )

    def get_line_number(text: str, pos: int) -> int:
        """Get line number for a position in text."""
        return text[:pos].count('\n') + 1

    # Check triple-quoted strings
    for match in triple_quote_pattern.finditer(content):
        prefix = match.group(1).lower()
        string_content = match.group(3)

        # Skip if it's an f-string (has 'f' in prefix)
        if 'f' in prefix:
            continue

        # Skip if there's a suppress marker nearby
        if has_suppress_marker(content, match.start()):
            continue

        # Skip if followed by .format() - this is intentional template usage
        if is_format_string(content, match.end()):
            continue

        # Check if it looks like SQL
        if not is_sql_string(string_content):
            continue

        # Check for variable patterns
        var_patterns = find_variable_patterns(string_content)
        if var_patterns:
            line_num = get_line_number(content, match.start())
            # Get a preview of the string (first line with content)
            preview_lines = [
                line.strip() for line in string_content.split('\n')
                if line.strip()
            ]
            preview = preview_lines[0][:80] if preview_lines else string_content[:80]

            # Check if this is a docstring (the triple-quoted string itself is a docstring)
            in_docstring = is_in_docstring(content, match.start(), docstring_ranges)

            issues.append(Issue(
                file=str(file_path),
                line=line_num,
                preview=preview,
                variable_patterns=var_patterns[:5],  # Limit to first 5
                in_docstring=in_docstring
            ))

    # Check single-line strings too (less common but possible)
    for match in single_quote_pattern.finditer(content):
        prefix = match.group(1).lower()
        string_content = match.group(3)

        # Skip if it's an f-string
        if 'f' in prefix:
            continue

        # Skip if there's a suppress marker nearby
        if has_suppress_marker(content, match.start()):
            continue

        # Skip if followed by .format() - this is intentional template usage
        if is_format_string(content, match.end()):
            continue

        # Skip short strings (unlikely to be SQL queries)
        if len(string_content) < 20:
            continue

        # Check if it looks like SQL
        if not is_sql_string(string_content):
            continue

        # Check for variable patterns
        var_patterns = find_variable_patterns(string_content)
        if var_patterns:
            line_num = get_line_number(content, match.start())
            preview = string_content[:80]

            # Check if this single-line string is inside a docstring
            in_docstring = is_in_docstring(content, match.start(), docstring_ranges)

            issues.append(Issue(
                file=str(file_path),
                line=line_num,
                preview=preview,
                variable_patterns=var_patterns[:5],
                in_docstring=in_docstring
            ))

    return issues


def main() -> int:
    """Main entry point."""
    # Get files to check
    if len(sys.argv) > 1:
        files = [Path(f) for f in sys.argv[1:]]
    else:
        # If no files specified, check all Python files
        project_root = Path(__file__).parent.parent
        files = list(project_root.rglob('*.py'))

    # Filter to relevant files
    files = [f for f in files if should_check_file(f)]

    all_issues = []

    for file_path in files:
        issues = check_file(file_path)
        all_issues.extend(issues)

    # Separate docstring issues (warnings) from real issues (errors)
    real_issues = [i for i in all_issues if not i.in_docstring]
    docstring_issues = [i for i in all_issues if i.in_docstring]

    # Report findings
    if real_issues:
        print("=" * 70)
        print("SQL F-STRING CHECK: Missing f-prefix on SQL strings with variables")
        print("=" * 70)
        print()
        print("The following SQL strings contain variable patterns like {self.x}")
        print("but are missing the 'f' prefix, so variables won't be interpolated!")
        print()

        for issue in real_issues:
            print(f"File: {issue.file}:{issue.line}")
            print(f"  Preview: {issue.preview}...")
            print(f"  Uninterpolated: {', '.join(issue.variable_patterns)}")
            print()

        print("=" * 70)
        print(f"Total: {len(real_issues)} SQL strings with missing f-prefix")
        print()
        print("FIX: Add 'f' prefix to these strings:")
        print('  BEFORE: query = """SELECT * FROM `{self.project}.table`"""')
        print('  AFTER:  query = f"""SELECT * FROM `{self.project}.table`"""')
        print()
        print("If this is intentional (e.g., template string), add a comment:")
        print('  # sql-template')
        print('  query = """SELECT * FROM `{project}.table`"""')
        print("=" * 70)

    # Report docstring warnings (informational only)
    if docstring_issues:
        print()
        print("-" * 70)
        print("INFO: Found in docstrings (not blocking, but review if copy-pasted):")
        print("-" * 70)
        for issue in docstring_issues:
            print(f"  {issue.file}:{issue.line} - {', '.join(issue.variable_patterns)}")
        print()

    if real_issues:
        return 1  # Exit with error to block commit
    elif not all_issues:
        print("SQL f-string check: OK (no uninterpolated variables found)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
