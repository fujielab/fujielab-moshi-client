# Local Work Directory

This directory contains development and testing files that are not part of the main package installation.

## Contents

- `test_buffering.py` - Basic functionality tests for the enhanced buffering features
- `test_buffering_detailed.py` - Comprehensive tests with detailed analysis
- `example_enhanced_usage.py` - Usage examples demonstrating the new features
- `ENHANCED_FEATURES.md` - Complete documentation of the enhanced audio buffering functionality

## Usage

These files are for development, testing, and documentation purposes. They are excluded from the package installation via `pyproject.toml` configuration.

To run the tests:

```bash
cd local_work
python test_buffering.py
python test_buffering_detailed.py
python example_enhanced_usage.py
```

## Note

This directory is excluded from the package installation and should not be included in distributions.