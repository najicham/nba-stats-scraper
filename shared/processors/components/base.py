"""
Base classes for composable processor components.

This module defines the abstract interfaces for all component types
and the ComposableProcessor that assembles them.

Design Principles:
    1. Single Responsibility: Each component does one thing well
    2. Composability: Components can be combined in any order
    3. Testability: Components can be tested in isolation
    4. Configuration-driven: Behavior controlled via config, not code

Version: 1.0
Created: 2026-01-23
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    TypeVar,
    Union,
)

import pandas as pd
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Type variables for generic components
T = TypeVar('T')
InputT = TypeVar('InputT')
OutputT = TypeVar('OutputT')


@dataclass
class ComponentContext:
    """
    Shared context passed between components during processing.

    Contains runtime state and configuration that all components need access to.
    """
    # Processing parameters
    start_date: str
    end_date: str
    run_id: str

    # GCP clients
    bq_client: Optional[bigquery.Client] = None
    project_id: Optional[str] = None

    # Runtime state
    options: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    quality_issues: List[Dict] = field(default_factory=list)

    # Processing flags
    is_backfill: bool = False
    is_incremental: bool = False

    # Source tracking (populated by loaders)
    sources_used: List[str] = field(default_factory=list)
    source_metadata: Dict[str, Dict] = field(default_factory=dict)

    def add_metric(self, name: str, value: Any) -> None:
        """Add a metric to the context."""
        self.metrics[name] = value

    def add_quality_issue(
        self,
        issue_type: str,
        severity: str,
        identifier: str,
        details: Dict = None
    ) -> None:
        """Record a quality issue."""
        self.quality_issues.append({
            'issue_type': issue_type,
            'severity': severity,
            'identifier': identifier,
            'details': details or {},
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })

    def add_source(self, source_name: str, metadata: Dict = None) -> None:
        """Record a source that was used."""
        if source_name not in self.sources_used:
            self.sources_used.append(source_name)
        if metadata:
            self.source_metadata[source_name] = metadata


class Component(ABC):
    """
    Base class for all processor components.

    Components are stateless and receive all context via the process() method.
    This enables easy testing and reuse across processors.
    """

    def __init__(self, name: Optional[str] = None):
        """
        Initialize component.

        Args:
            name: Optional name for this component instance
        """
        self.name = name or self.__class__.__name__

    @abstractmethod
    def process(self, data: Any, context: ComponentContext) -> Any:
        """
        Process data using this component.

        Args:
            data: Input data (type depends on component)
            context: Shared processing context

        Returns:
            Processed data (type depends on component)
        """
        pass

    def validate_config(self) -> List[str]:
        """
        Validate component configuration.

        Returns:
            List of validation error messages (empty if valid)
        """
        return []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"


class DataLoader(Component):
    """
    Base class for data loading components.

    DataLoaders are responsible for:
    - Querying data sources (BigQuery, GCS, APIs)
    - Handling connection errors with retries
    - Tracking source metadata
    - Supporting fallback chains

    Input: ComponentContext (no data input)
    Output: pd.DataFrame
    """

    @abstractmethod
    def load(self, context: ComponentContext) -> pd.DataFrame:
        """
        Load data from the source.

        Args:
            context: Processing context with dates and options

        Returns:
            DataFrame with loaded data
        """
        pass

    def process(self, data: Any, context: ComponentContext) -> pd.DataFrame:
        """
        Process method for component interface.

        For loaders, this delegates to load() and ignores input data.
        """
        return self.load(context)


class Validator(Component):
    """
    Base class for data validation components.

    Validators are responsible for:
    - Checking required fields exist
    - Validating data types
    - Detecting statistical anomalies
    - Recording quality issues

    Input: pd.DataFrame
    Output: pd.DataFrame (same data, with issues recorded in context)
    """

    @abstractmethod
    def validate(
        self,
        data: pd.DataFrame,
        context: ComponentContext
    ) -> pd.DataFrame:
        """
        Validate data and record any issues.

        Args:
            data: DataFrame to validate
            context: Processing context (issues recorded here)

        Returns:
            Same DataFrame (validation is side-effect on context)
        """
        pass

    def process(
        self,
        data: pd.DataFrame,
        context: ComponentContext
    ) -> pd.DataFrame:
        """Process method for component interface."""
        return self.validate(data, context)


class Transformer(Component):
    """
    Base class for data transformation components.

    Transformers are responsible for:
    - Computing derived fields
    - Mapping field names
    - Calculating analytics metrics
    - Adding quality metadata

    Input: pd.DataFrame or List[Dict]
    Output: List[Dict] (records ready for output)
    """

    @abstractmethod
    def transform(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """
        Transform data into output records.

        Args:
            data: Input data (DataFrame or list of dicts)
            context: Processing context

        Returns:
            List of output record dictionaries
        """
        pass

    def process(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        context: ComponentContext
    ) -> List[Dict]:
        """Process method for component interface."""
        return self.transform(data, context)


class OutputWriter(Component):
    """
    Base class for output writing components.

    Writers are responsible for:
    - Writing data to destinations (BigQuery, GCS, etc.)
    - Handling write conflicts (MERGE vs INSERT)
    - Tracking write metrics

    Input: List[Dict]
    Output: Dict with write statistics
    """

    @abstractmethod
    def write(
        self,
        records: List[Dict],
        context: ComponentContext
    ) -> Dict[str, int]:
        """
        Write records to destination.

        Args:
            records: List of record dictionaries to write
            context: Processing context

        Returns:
            Dict with statistics: {records_written, records_updated, etc.}
        """
        pass

    def process(
        self,
        data: List[Dict],
        context: ComponentContext
    ) -> Dict[str, int]:
        """Process method for component interface."""
        return self.write(data, context)


@dataclass
class ProcessorConfig:
    """
    Configuration for a composable processor.

    This dataclass defines all the components and settings for a processor.
    """
    # Processor identity
    name: str
    table_name: str
    dataset_id: str = 'nba_analytics'

    # Processing components
    loaders: List[DataLoader] = field(default_factory=list)
    validators: List[Validator] = field(default_factory=list)
    transformers: List[Transformer] = field(default_factory=list)
    writers: List[OutputWriter] = field(default_factory=list)

    # Dependency configuration
    dependencies: Dict[str, Dict] = field(default_factory=dict)

    # Hash configuration for change detection
    hash_fields: List[str] = field(default_factory=list)
    primary_key_fields: List[str] = field(default_factory=list)

    # Processing strategy
    processing_strategy: str = 'MERGE_UPDATE'

    # Optional: Custom hooks
    pre_process_hook: Optional[Callable] = None
    post_process_hook: Optional[Callable] = None

    def validate(self) -> List[str]:
        """Validate configuration completeness."""
        errors = []

        if not self.name:
            errors.append("Processor name is required")
        if not self.table_name:
            errors.append("Table name is required")
        if not self.loaders:
            errors.append("At least one loader is required")
        if not self.writers:
            errors.append("At least one writer is required")

        # Validate individual components
        for component in self.loaders + self.validators + self.transformers + self.writers:
            errors.extend(component.validate_config())

        return errors


class ComposableProcessor:
    """
    Base class for processors built from composable components.

    This class orchestrates the component pipeline:
    1. Load data using loaders
    2. Validate data using validators
    3. Transform data using transformers
    4. Write output using writers

    Usage:
        class MyProcessor(ComposableProcessor):
            @classmethod
            def get_config(cls) -> ProcessorConfig:
                return ProcessorConfig(
                    name='my_processor',
                    table_name='my_table',
                    loaders=[...],
                    validators=[...],
                    transformers=[...],
                    writers=[...],
                )

        processor = MyProcessor()
        success = processor.run({'start_date': '2025-01-01', 'end_date': '2025-01-01'})
    """

    def __init__(self, config: Optional[ProcessorConfig] = None):
        """
        Initialize processor with configuration.

        Args:
            config: Optional config (if not provided, get_config() is called)
        """
        self.config = config or self.get_config()
        self._validate_config()

        # Runtime state
        self.context: Optional[ComponentContext] = None
        self.raw_data: Optional[pd.DataFrame] = None
        self.transformed_data: Optional[List[Dict]] = None
        self.stats: Dict[str, Any] = {}

    @classmethod
    def get_config(cls) -> ProcessorConfig:
        """
        Get processor configuration.

        Subclasses must override this to provide their configuration.
        """
        raise NotImplementedError("Subclasses must implement get_config()")

    def _validate_config(self) -> None:
        """Validate configuration on initialization."""
        errors = self.config.validate()
        if errors:
            raise ValueError(f"Invalid processor config: {', '.join(errors)}")

    def _create_context(self, opts: Dict[str, Any]) -> ComponentContext:
        """Create processing context from options."""
        import uuid
        import os

        # Get or create BigQuery client
        from shared.clients.bigquery_pool import get_bigquery_client

        project_id = os.environ.get('GCP_PROJECT_ID', 'your-project-id')
        bq_client = get_bigquery_client(project_id=project_id)

        return ComponentContext(
            start_date=opts['start_date'],
            end_date=opts['end_date'],
            run_id=str(uuid.uuid4())[:8],
            bq_client=bq_client,
            project_id=project_id,
            options=opts,
            is_backfill=opts.get('backfill_mode', False),
            is_incremental=opts.get('incremental', False),
        )

    def run(self, opts: Dict[str, Any]) -> bool:
        """
        Execute the processor pipeline.

        Args:
            opts: Processing options (must include start_date, end_date)

        Returns:
            True on success, False on failure
        """
        try:
            # Validate options
            if 'start_date' not in opts or 'end_date' not in opts:
                raise ValueError("start_date and end_date are required")

            # Create context
            self.context = self._create_context(opts)
            logger.info(
                f"Starting {self.config.name} processor "
                f"(run_id={self.context.run_id}, "
                f"dates={self.context.start_date} to {self.context.end_date})"
            )

            # Pre-process hook
            if self.config.pre_process_hook:
                self.config.pre_process_hook(self.context)

            # Execute pipeline stages
            self._execute_load()
            self._execute_validate()
            self._execute_transform()
            write_stats = self._execute_write()

            # Record statistics
            self.stats.update({
                'run_id': self.context.run_id,
                'records_processed': len(self.transformed_data) if self.transformed_data else 0,
                'sources_used': self.context.sources_used,
                'quality_issues': len(self.context.quality_issues),
                **write_stats,
            })

            # Post-process hook
            if self.config.post_process_hook:
                self.config.post_process_hook(self.context, self.stats)

            logger.info(
                f"Completed {self.config.name}: "
                f"{self.stats.get('records_processed', 0)} records processed"
            )

            return True

        except Exception as e:
            logger.error(f"{self.config.name} failed: {e}", exc_info=True)
            self.stats['error'] = str(e)
            return False

    def _execute_load(self) -> None:
        """Execute data loading stage."""
        logger.info(f"Loading data with {len(self.config.loaders)} loader(s)")

        # If multiple loaders, concatenate results
        dataframes = []
        for loader in self.config.loaders:
            df = loader.process(None, self.context)
            if df is not None and not df.empty:
                dataframes.append(df)

        if dataframes:
            self.raw_data = pd.concat(dataframes, ignore_index=True)
        else:
            self.raw_data = pd.DataFrame()

        logger.info(f"Loaded {len(self.raw_data)} records")
        self.context.add_metric('records_loaded', len(self.raw_data))

    def _execute_validate(self) -> None:
        """Execute data validation stage."""
        if self.raw_data is None or self.raw_data.empty:
            logger.info("No data to validate")
            return

        logger.info(f"Validating data with {len(self.config.validators)} validator(s)")

        data = self.raw_data
        for validator in self.config.validators:
            data = validator.process(data, self.context)

        self.raw_data = data

        if self.context.quality_issues:
            logger.warning(
                f"Validation found {len(self.context.quality_issues)} quality issues"
            )

    def _execute_transform(self) -> None:
        """Execute data transformation stage."""
        if self.raw_data is None or self.raw_data.empty:
            logger.info("No data to transform")
            self.transformed_data = []
            return

        logger.info(f"Transforming data with {len(self.config.transformers)} transformer(s)")

        # Start with DataFrame, end with List[Dict]
        data = self.raw_data
        for transformer in self.config.transformers:
            data = transformer.process(data, self.context)

        self.transformed_data = data if isinstance(data, list) else data.to_dict('records')
        logger.info(f"Transformed into {len(self.transformed_data)} output records")

    def _execute_write(self) -> Dict[str, int]:
        """Execute output writing stage."""
        if not self.transformed_data:
            logger.info("No data to write")
            return {'records_written': 0}

        logger.info(
            f"Writing {len(self.transformed_data)} records "
            f"with {len(self.config.writers)} writer(s)"
        )

        combined_stats = {}
        for writer in self.config.writers:
            stats = writer.process(self.transformed_data, self.context)
            combined_stats.update(stats)

        return combined_stats

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        return self.stats.copy()
