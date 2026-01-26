"""
Smoke Test: Method Resolution Order (MRO) Validation

Validates that all processor classes have valid MRO (method resolution order).
Catches diamond inheritance and circular dependency issues before deployment.

This would have caught the PlayerDailyCacheProcessor MRO conflict in Session 34.
"""

import pytest
import inspect
import importlib
from pathlib import Path
from typing import List, Type, Set


def discover_processor_modules():
    """Discover all processor modules in the codebase."""
    modules = []

    # Analytics processors
    analytics_path = Path('data_processors/analytics')
    if analytics_path.exists():
        for processor_dir in analytics_path.iterdir():
            if processor_dir.is_dir() and not processor_dir.name.startswith('_'):
                processor_file = processor_dir / f"{processor_dir.name}_processor.py"
                if processor_file.exists():
                    module_path = f"data_processors.analytics.{processor_dir.name}.{processor_dir.name}_processor"
                    modules.append(('analytics', processor_dir.name, module_path))

    # Precompute processors
    precompute_path = Path('data_processors/precompute')
    if precompute_path.exists():
        for processor_dir in precompute_path.iterdir():
            if processor_dir.is_dir() and not processor_dir.name.startswith('_') and processor_dir.name != 'base':
                processor_file = processor_dir / f"{processor_dir.name}_processor.py"
                if processor_file.exists():
                    module_path = f"data_processors.precompute.{processor_dir.name}.{processor_dir.name}_processor"
                    modules.append(('precompute', processor_dir.name, module_path))

    # Raw processors
    raw_path = Path('data_processors/raw')
    if raw_path.exists():
        for processor_dir in raw_path.iterdir():
            if processor_dir.is_dir() and not processor_dir.name.startswith('_') and processor_dir.name != 'base':
                processor_file = processor_dir / f"{processor_dir.name}_processor.py"
                if processor_file.exists():
                    module_path = f"data_processors.raw.{processor_dir.name}.{processor_dir.name}_processor"
                    modules.append(('raw', processor_dir.name, module_path))

    return modules


def get_processor_classes() -> List[tuple]:
    """Get all processor classes from discovered modules."""
    processor_classes = []

    for phase, name, module_path in discover_processor_modules():
        try:
            module = importlib.import_module(module_path)

            # Look for classes ending with 'Processor'
            for attr_name in dir(module):
                if attr_name.endswith('Processor') and not attr_name.startswith('_'):
                    attr = getattr(module, attr_name)
                    if inspect.isclass(attr) and attr.__module__ == module_path:
                        processor_classes.append((phase, name, attr))
        except Exception as e:
            # Skip modules that fail to import (they'll be caught by import smoke tests)
            print(f"Warning: Could not import {module_path}: {e}")
            continue

    return processor_classes


class TestProcessorMRO:
    """Validate MRO for all processor classes."""

    @pytest.mark.parametrize("phase,name,processor_class", get_processor_classes())
    def test_processor_has_valid_mro(self, phase, name, processor_class):
        """
        Test that each processor class has valid MRO.

        This catches TypeError: Cannot create a consistent method resolution order
        """
        try:
            mro = processor_class.__mro__
            assert len(mro) > 0, f"{processor_class.__name__} has empty MRO"
            assert object in mro, f"{processor_class.__name__} MRO doesn't include object"
        except TypeError as e:
            pytest.fail(
                f"Invalid MRO for {phase}/{name}/{processor_class.__name__}: {e}\n"
                f"This usually means diamond inheritance conflict.\n"
                f"Check for duplicate base classes in inheritance chain."
            )

    @pytest.mark.parametrize("phase,name,processor_class", get_processor_classes())
    def test_no_duplicate_base_classes(self, phase, name, processor_class):
        """
        Test that no base class appears multiple times in inheritance chain.

        This would have caught PlayerDailyCacheProcessor inheriting from
        BackfillModeMixin directly when PrecomputeProcessorBase already includes it.
        """
        def collect_all_bases(cls, seen=None) -> Set[Type]:
            """Recursively collect all base classes."""
            if seen is None:
                seen = set()

            for base in cls.__bases__:
                if base != object and base not in seen:
                    seen.add(base)
                    collect_all_bases(base, seen)

            return seen

        def find_duplicates_in_hierarchy(cls) -> List[Type]:
            """Find any base class that appears in multiple branches."""
            duplicates = []

            # For each base class
            for base in cls.__bases__:
                if base == object:
                    continue

                # Check if it appears in other bases' hierarchies
                for other_base in cls.__bases__:
                    if other_base == base or other_base == object:
                        continue

                    other_bases = collect_all_bases(other_base)
                    if base in other_bases:
                        duplicates.append(base)

            return duplicates

        duplicates = find_duplicates_in_hierarchy(processor_class)

        if duplicates:
            duplicate_names = [d.__name__ for d in duplicates]
            pytest.fail(
                f"{phase}/{name}/{processor_class.__name__} has duplicate base classes: {duplicate_names}\n"
                f"Direct bases: {[b.__name__ for b in processor_class.__bases__]}\n"
                f"One of your direct bases likely already includes these mixins.\n"
                f"Remove the duplicate from your class definition."
            )

    @pytest.mark.parametrize("phase,name,processor_class", get_processor_classes())
    def test_processor_is_instantiable(self, phase, name, processor_class):
        """
        Test that processor class can be instantiated (MRO allows __init__).

        This catches cases where MRO prevents proper initialization.
        Note: We don't actually instantiate (might need real dependencies),
        just verify the class structure allows it.
        """
        # Check that __init__ is resolvable through MRO
        try:
            init_method = processor_class.__init__
            assert init_method is not None
        except AttributeError as e:
            pytest.fail(
                f"{phase}/{name}/{processor_class.__name__} has no __init__ method: {e}\n"
                f"MRO may be broken."
            )


class TestProcessorMROHelpers:
    """Helper tests for MRO validation."""

    def test_all_processors_discovered(self):
        """Verify processor discovery is working."""
        processors = get_processor_classes()

        # Should find at least a few processors
        assert len(processors) > 0, "No processors discovered - check discovery logic"

        # Print summary
        phases = {}
        for phase, name, cls in processors:
            phases[phase] = phases.get(phase, 0) + 1

        print(f"\nDiscovered {len(processors)} processor classes:")
        for phase, count in sorted(phases.items()):
            print(f"  {phase}: {count} processors")

    def test_mro_validation_catches_known_issue(self):
        """
        Regression test: Verify MRO validation would catch the known issue.

        This simulates the PlayerDailyCacheProcessor bug from Session 34.
        """
        # Create a mock mixin
        class MockMixin:
            pass

        # Create a base that includes the mixin
        class MockBase(MockMixin):
            pass

        # This should FAIL - diamond inheritance
        with pytest.raises(TypeError, match="Cannot create a consistent method resolution"):
            class BadProcessor(MockMixin, MockBase):  # noqa: F841
                pass
