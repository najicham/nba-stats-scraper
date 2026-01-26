"""
File: data_processors/precompute/mixins/backfill_mode_mixin.py

Mixin for backfill mode detection and validation.

This mixin provides methods for:
- Detecting backfill mode from various flag configurations
- Validating and normalizing backfill-related flags
- Logging backfill mode status clearly

Required Dependencies (must be provided by the class using this mixin):
- self.opts: Dict - Processing options dictionary
- self.backfill_mode: bool - Backfill mode flag (optional, derived from opts)
- self.skip_if_exists: bool - Skip if exists flag (optional)
- self.force_reprocess: bool - Force reprocess flag (optional)

Version: 1.0
Created: 2026-01-25
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class BackfillModeMixin:
    """
    Mixin for backfill mode detection and validation.

    Provides methods to detect backfill mode from various flag configurations
    and validate/normalize backfill-related flags.

    Required attributes (must be provided by the class using this mixin):
    - self.opts: Dict[str, Any] - Processing options dictionary

    Optional attributes (used if available):
    - self.backfill_mode: bool - Backfill mode flag
    - self.skip_if_exists: bool - Skip if exists flag
    - self.force_reprocess: bool - Force reprocess flag
    """

    # Type hints for required dependencies (set by the class using this mixin)
    opts: Dict[str, Any]
    backfill_mode: bool
    skip_if_exists: bool
    force_reprocess: bool

    @property
    def is_backfill_mode(self) -> bool:
        """
        Detect if we're in backfill mode.

        Backfill mode indicators (in order of preference):
        - backfill_mode=True in opts (preferred)
        - is_backfill=True in opts (legacy alias - supported but logs warning)
        - skip_downstream_trigger=True (implies backfill)

        Returns:
            bool: True if in backfill mode
        """
        return (
            self.opts.get('backfill_mode', False) or
            self.opts.get('is_backfill', False) or  # Legacy alias for backwards compatibility
            self.opts.get('skip_downstream_trigger', False)
        )

    def _validate_and_normalize_backfill_flags(self) -> None:
        """
        Validate backfill-related flags and normalize to canonical form.

        This method:
        1. Detects incorrect/legacy flag names and logs warnings
        2. Normalizes flags to the canonical 'backfill_mode' key
        3. Logs clearly when backfill mode is active

        Called early in run() to catch configuration issues.
        """
        # Check for legacy 'is_backfill' flag (common mistake)
        if self.opts.get('is_backfill', False) and not self.opts.get('backfill_mode', False):
            logger.warning(
                "⚠️  DEPRECATION: Using 'is_backfill=True' - please use 'backfill_mode=True' instead. "
                "Backfill mode will still be activated for backwards compatibility."
            )
            # Normalize to canonical form
            self.opts['backfill_mode'] = True

        # Check for common typos/mistakes
        suspicious_keys = ['backfill', 'isBackfill', 'is_back_fill', 'backfillMode']
        for key in suspicious_keys:
            if key in self.opts:
                logger.error(
                    f"❌ INVALID FLAG: '{key}' is not a valid backfill flag. "
                    f"Use 'backfill_mode=True' instead. Current value: {self.opts[key]}"
                )
                raise ValueError(
                    f"Invalid backfill flag '{key}'. Use 'backfill_mode=True' for backfill processing."
                )

        # Log backfill mode status clearly
        if self.is_backfill_mode:
            active_flags = []
            if self.opts.get('backfill_mode'):
                active_flags.append('backfill_mode=True')
            if self.opts.get('is_backfill'):
                active_flags.append('is_backfill=True (legacy)')
            if self.opts.get('skip_downstream_trigger'):
                active_flags.append('skip_downstream_trigger=True')

            logger.info(
                f"🔄 BACKFILL MODE ACTIVE: Completeness checks will be SKIPPED. "
                f"Active flags: {', '.join(active_flags)}"
            )
        else:
            logger.info(
                "📋 PRODUCTION MODE: Completeness checks will be ENFORCED. "
                "Use backfill_mode=True to skip checks for historical processing."
            )
