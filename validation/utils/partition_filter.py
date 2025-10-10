#!/usr/bin/env python3
# File: validation/utils/partition_filter.py
# Description: Partition Filter Handler - Ensures all queries include required partition filters for cost optimization
"""
Partition Filter Handler
Ensures all queries include required partition filters for cost optimization
"""

import re
from typing import Optional
from datetime import date, timedelta


class PartitionFilterError(Exception):
    """Raised when a required partition filter is missing"""
    pass


class PartitionFilterHandler:
    """
    Handles automatic injection and validation of partition filters.
    
    Usage:
        handler = PartitionFilterHandler(
            table='nba_raw.espn_scoreboard',
            partition_field='game_date',
            required=True
        )
        
        # Automatically adds partition filter
        safe_query = handler.ensure_partition_filter(
            query="SELECT * FROM `nba_raw.espn_scoreboard`",
            start_date='2024-11-01',
            end_date='2024-11-30'
        )
    """
    
    def __init__(
        self, 
        table: str, 
        partition_field: str = 'game_date',
        required: bool = True
    ):
        self.table = table
        self.partition_field = partition_field
        self.required = required
    
    def ensure_partition_filter(
        self, 
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> str:
        """
        Ensure query has partition filter, add if missing.
        
        Args:
            query: SQL query string
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        
        Returns:
            Query with partition filter guaranteed
        
        Raises:
            PartitionFilterError: If required filter missing and can't add automatically
        """
        # Check if partition filter already exists
        if self._has_partition_filter(query):
            return query
        
        # If not required, just return original query
        if not self.required:
            return query
        
        # Required but missing - try to add automatically
        if not start_date or not end_date:
            raise PartitionFilterError(
                f"Query on {self.table} requires partition filter on {self.partition_field}, "
                f"but no date range provided"
            )
        
        return self._inject_partition_filter(query, start_date, end_date)
    
    def _has_partition_filter(self, query: str) -> bool:
        """Check if query already has partition filter"""
        
        # Look for common partition filter patterns
        patterns = [
            # game_date >= '2024-01-01'
            rf"{self.partition_field}\s*>=\s*['\"][\d-]+['\"]",
            # game_date <= '2024-01-31'
            rf"{self.partition_field}\s*<=\s*['\"][\d-]+['\"]",
            # game_date BETWEEN '2024-01-01' AND '2024-01-31'
            rf"{self.partition_field}\s+BETWEEN\s+['\"][\d-]+['\"]",
            # game_date = '2024-01-01'
            rf"{self.partition_field}\s*=\s*['\"][\d-]+['\"]",
            # game_date IN ('2024-01-01', '2024-01-02')
            rf"{self.partition_field}\s+IN\s*\(",
        ]
        
        query_upper = query.upper()
        partition_field_upper = self.partition_field.upper()
        
        for pattern in patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        
        return False
    
    def _inject_partition_filter(
        self, 
        query: str, 
        start_date: str, 
        end_date: str
    ) -> str:
        """
        Inject partition filter into query.
        
        Handles these patterns:
        - Simple SELECT with WHERE
        - Simple SELECT without WHERE
        - CTE queries
        - Subqueries
        """
        
        # Normalize query
        query = query.strip()
        
        # Build partition filter clause
        filter_clause = (
            f"{self.partition_field} >= '{start_date}' "
            f"AND {self.partition_field} <= '{end_date}'"
        )
        
        # Pattern 1: Query has WHERE clause
        if re.search(r'\bWHERE\b', query, re.IGNORECASE):
            # Find WHERE clause and add partition filter with AND
            query = re.sub(
                r'(\bWHERE\b\s+)',
                rf'\1{filter_clause} AND ',
                query,
                count=1,
                flags=re.IGNORECASE
            )
            return query
        
        # Pattern 2: Query has no WHERE but has FROM clause
        # Find the main FROM clause (not in subqueries)
        from_match = re.search(
            rf'\bFROM\b\s+`?{re.escape(self.table)}`?',
            query,
            re.IGNORECASE
        )
        
        if from_match:
            # Insert WHERE clause after FROM table_name
            insert_pos = from_match.end()
            
            # Check if there's a JOIN, GROUP BY, ORDER BY, or LIMIT after FROM
            # If so, insert before that
            for keyword in ['JOIN', 'GROUP BY', 'ORDER BY', 'LIMIT', 'HAVING']:
                keyword_match = re.search(
                    rf'\b{keyword}\b',
                    query[insert_pos:],
                    re.IGNORECASE
                )
                if keyword_match:
                    # Insert WHERE before this keyword
                    actual_pos = insert_pos + keyword_match.start()
                    return (
                        query[:actual_pos] +
                        f"\nWHERE {filter_clause}\n" +
                        query[actual_pos:]
                    )
            
            # No keywords found, insert at end
            return query + f"\nWHERE {filter_clause}"
        
        # Pattern 3: Complex query (CTE, subquery) - can't inject safely
        if 'WITH' in query.upper() or '(' in query:
            raise PartitionFilterError(
                f"Cannot automatically inject partition filter into complex query. "
                f"Please add manually: WHERE {filter_clause}"
            )
        
        # Fallback: couldn't inject
        raise PartitionFilterError(
            f"Could not inject partition filter. Please add manually: "
            f"WHERE {filter_clause}"
        )
    
    def validate_date_range(
        self, 
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> tuple[str, str]:
        """
        Validate and normalize date range.
        
        Returns:
            (start_date, end_date) as ISO strings
        """
        if not start_date or not end_date:
            # Use default range (last 30 days)
            end = date.today()
            start = end - timedelta(days=30)
            return start.isoformat(), end.isoformat()
        
        # Validate format
        try:
            date.fromisoformat(start_date)
            date.fromisoformat(end_date)
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")
        
        return start_date, end_date
    
    def get_partition_info(self) -> dict:
        """Get partition configuration info"""
        return {
            'table': self.table,
            'partition_field': self.partition_field,
            'required': self.required
        }


# ============================================================================
# Helper Functions
# ============================================================================

def create_partition_handler(config: dict) -> Optional[PartitionFilterHandler]:
    """
    Create partition handler from processor config.
    
    Args:
        config: Processor config dict with 'processor' section
    
    Returns:
        PartitionFilterHandler or None if not required
    """
    processor_config = config.get('processor', {})
    
    partition_required = processor_config.get('partition_required', False)
    
    if not partition_required:
        return None
    
    table = processor_config.get('table')
    partition_field = processor_config.get('partition_field', 'game_date')
    
    if not table:
        raise ValueError("Config missing 'table' field but partition_required=True")
    
    return PartitionFilterHandler(
        table=table,
        partition_field=partition_field,
        required=True
    )


# ============================================================================
# Examples
# ============================================================================

if __name__ == "__main__":
    # Example 1: Simple query with WHERE
    handler = PartitionFilterHandler(
        table='nba_raw.espn_scoreboard',
        partition_field='game_date',
        required=True
    )
    
    query1 = """
    SELECT *
    FROM `nba_raw.espn_scoreboard`
    WHERE home_team_abbr = 'LAL'
    """
    
    safe_query1 = handler.ensure_partition_filter(
        query1,
        start_date='2024-11-01',
        end_date='2024-11-30'
    )
    
    print("Example 1 - Query with WHERE:")
    print(safe_query1)
    print()
    
    # Example 2: Simple query without WHERE
    query2 = """
    SELECT *
    FROM `nba_raw.espn_scoreboard`
    ORDER BY game_date DESC
    """
    
    safe_query2 = handler.ensure_partition_filter(
        query2,
        start_date='2024-11-01',
        end_date='2024-11-30'
    )
    
    print("Example 2 - Query without WHERE:")
    print(safe_query2)
    print()
    
    # Example 3: Query that already has partition filter
    query3 = """
    SELECT *
    FROM `nba_raw.espn_scoreboard`
    WHERE game_date >= '2024-11-01'
      AND game_date <= '2024-11-30'
      AND is_completed = TRUE
    """
    
    safe_query3 = handler.ensure_partition_filter(
        query3,
        start_date='2024-11-01',
        end_date='2024-11-30'
    )
    
    print("Example 3 - Query already has filter:")
    print(safe_query3)
    print()
    
    # Example 4: Check if query has filter
    print(f"Query 1 has filter: {handler._has_partition_filter(query1)}")
    print(f"Query 2 has filter: {handler._has_partition_filter(query2)}")
    print(f"Query 3 has filter: {handler._has_partition_filter(query3)}")