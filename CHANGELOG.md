# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] — 2025-09

### Added
- Initial release
- PDF reader (Module 1): pdfplumber-based word extraction with y-proximity line grouping
- Section detector (Module 2): competition header, section boundaries, column headers
- Athlete assembler (Module 3): 1–4 printed line grouping, target-code stripping, club parsing
- Transformer (Module 4): lookup tables, name/club formatting, per-end row expansion
- Writer (Module 5): arithmetic verification (subtotals + grand totals) + UTF-8 CSV output
- CLI with `--output`, `--append`, `--verbose`, `--dry-run`, `--log`, `--encoding` flags
- Support for 72-arrow and 144-arrow qualification rounds
- All four bow types: Recurve, Compound, Barebow, Longbow
- All age/gender classes: Adult, U21, U18, U15, U13, U10, +50, Harrastajad
- Uniform and mixed-distance rounds (e.g. 2×40m + 2×30m)
- 223 unit tests; integration test suite gated on PDF fixture
