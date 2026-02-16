# Remaining Fix Prompts for IANSEO PDF Parser

## Current Status: 14/20 Files Working (70%)

### ✅ Completed Fixes (Prompts 1-3)
1. **Arithmetic Mismatch Bug** - Fixed 409+ mismatches (rank parsing issue)
2. **Date Parser Error** - Fixed 4 files with MM-DD-YYYY format crash
3. **Empty Distances IndexError** - Fixed 1440_tulemused.pdf crash

---

## 🔧 Priority 1: Fix 7 Files with 0 Athletes Detected

### Prompt 4: Handle Lowercase Estonian Gender Tokens and Missing Sentinel Lines
**Priority: HIGH** (Blocks 7 files from parsing)

**Issue**: Parser detects 0 athletes in 7 files due to:
1. **Case-sensitive gender lookup** - Estonian tokens like "mehed", "naised" are lowercase but dictionary has "Mehed", "Naised"
2. **Missing "After N Arrows" sentinel** - 4 files have no sentinel line; detector stays in BETWEEN state forever
3. **Missing gender-neutral tokens** - "täiskasvanud" (adults), "algajad" (beginners) not in dictionary

**Files affected**:
- KaleviMV_eelring.pdf (no sentinel + lowercase)
- Karoline-Cup.pdf (no sentinel + lowercase + täiskasvanud)
- Lumemangud_eelring.pdf (no sentinel + lowercase)
- Rapla-mk-MV_eelring.pdf (no sentinel + lowercase + täiskasvanud)
- Jarvakandi-Kand-Eelring.pdf (has sentinel, lowercase + täiskasvanud)
- KV_eelring.pdf (has sentinel, lowercase)
- Visa-HIng_protokoll.pdf (has sentinel, lowercase + multi-line format)

**Root causes**:

1. **Case-sensitive lookup** in `detector.py:_parse_section_class_code()`:
   ```python
   if token in _GENDER_TOKEN:  # Case-sensitive!
       gender = _GENDER_TOKEN[token]
   ```
   PDFs have lowercase: "mehed", "naised", "noormehed", "poisid", "neiud", "tüdrukud"
   Dictionary has capitalized: "Mehed", "Naised", "Noormehed", etc.

2. **Missing sentinel line**: Files go directly from 3-line header to section titles like:
   ```
   Eesti Meistrivõistlused 2025
   Organizer (Code)
   Venue, Date
   Sportvibu - mehed          ← No "After 72 Arrows" before this
   Pos. Athlete Cat. Country...
   ```
   Detector never transitions from BETWEEN state to EXPECT_TITLE.

3. **Missing tokens**: "täiskasvanud" and "algajad" not in `_GENDER_TOKEN` dictionary.

**Task**:

1. **Fix case-insensitive lookup** in `detector.py:_parse_section_class_code()`:
   - Change `_GENDER_TOKEN` keys to lowercase
   - Use `token.lower()` for lookup
   - Update all references

2. **Add missing Estonian tokens** to `_GENDER_TOKEN`:
   ```python
   "täiskasvanud": "M",  # Adults (default to M, needs gender inference)
   "algajad": "M",       # Beginners (default to M, needs gender inference)
   ```
   Note: These are gender-neutral. Parser should warn when using default.

3. **Handle missing sentinel lines** in `detector.py:_detect_sections_impl()`:
   - Add alternative transition from BETWEEN → EXPECT_TITLE
   - When in BETWEEN state, check if line starts with known bow type prefix:
     - "Sportvibu" (Compound)
     - "Plokkvibu" (Compound)
     - "Recurve"
     - "Traditsiooniline vibu" (Traditional)
     - "Longbow" / "Pikkvibud"
   - If found, treat as section title and transition to EXPECT_COL_HDR
   - Extract arrow count from context if available (e.g., from column headers "18m-1" through "18m-4" = 72 arrows)

4. **Test on all 7 files** to verify they now detect sections:
   - Files should produce > 0 athletes
   - Verify gender/age detection works with lowercase tokens
   - Check files without sentinels parse correctly

5. **Do NOT test all 20 files** - only test the 7 affected files

**Expected results**:
- Jarvakandi-Kand-Eelring.pdf: ~20 athletes (has sentinel, needs case fix + täiskasvanud)
- KV_eelring.pdf: ~140 athletes (has sentinel, needs case fix)
- KaleviMV_eelring.pdf: ~20 athletes (no sentinel + case fix)
- Karoline-Cup.pdf: ~8 athletes (no sentinel + case fix + täiskasvanud)
- Lumemangud_eelring.pdf: ~26 athletes (no sentinel + case fix)
- Rapla-mk-MV_eelring.pdf: ~12 athletes (no sentinel + case fix + täiskasvanud)
- Visa-HIng_protokoll.pdf: May still fail (complex multi-line format - separate fix)

---

## 🔧 Priority 2: Special Format Handling

### Prompt 5: Handle Multi-line 216-Arrow Format (Visa-HIng)
**Priority: MEDIUM** (Blocks 1 file with unusual format)

**Issue**: Visa-HIng_protokoll.pdf has 216-arrow format (6 ends of 70m) with:
- Column headers split across 3 lines
- Athlete data split across 3 physical lines per athlete
- Interleaved header format:
  ```
  70m-1 70m-2 70m-3 70m-4 Tot.
  Pos. Athlete Cat. Country or State Code Total 10+X X
  70m-5 70m-6 Tot.
  ```

**File affected**: Visa-HIng_protokoll.pdf

**Root cause**: Current state machine expects:
1. Single column-header line with all distances
2. Single athlete data line with all scores

Actual format has:
- Line 1: "70m-1 70m-2 70m-3 70m-4 Tot."
- Line 2: "Pos. Athlete Cat. Country..."
- Line 3: "70m-5 70m-6 Tot."
- Then 3 lines per athlete:
  - Line A: Scores for ends 1-4
  - Line B: Athlete name, rank, total
  - Line C: Scores for ends 5-6

**Task**:

1. **Detect multi-line header pattern** in `detector.py`:
   - If current line has distance tokens AND next line is "Pos. Athlete..." AND line after that has distance tokens
   - Flag section as "multi-line format"
   - Merge distance tokens from lines 1 and 3

2. **Handle multi-line athlete parsing** in `parser.py`:
   - When section is flagged as multi-line format
   - Read 3 lines at a time:
     - Line A: Extract score values for first N ends
     - Line B: Extract athlete name, rank, total
     - Line C: Extract score values for remaining ends
   - Merge into single athlete record

3. **Test on Visa-HIng_protokoll.pdf** to verify:
   - Sections detected correctly
   - All 6 end scores parsed for each athlete
   - Names and totals extracted correctly

**Note**: This may require significant parser refactoring. Consider if this single file is worth the effort, or if manual processing is acceptable.

---

## 🔧 Priority 3: Minor Arithmetic Mismatches

### Prompt 6: Investigate and Fix Remaining Arithmetic Mismatches
**Priority: LOW** (Does not block parsing, just data quality issues)

**Issue**: 4 files have arithmetic mismatches where calculated totals don't match PDF totals:
- 1440_tulemused.pdf: 38 mismatches
- Eve-Suits-memoriaal-protokoll.pdf: 2 mismatches
- Jarvakandi-Open-25-protokoll.pdf: 1 mismatch
- Puiatu-CUP-2025-protokoll.pdf: 10 mismatches
- oige-Randme.csv: 1 mismatch

**Root cause**: Unknown - needs investigation. Possible causes:
1. **1440 round scoring** - Different calculation method for 4-distance rounds?
2. **Half-total assignment** - Wrong distance labels on half-total rows?
3. **Bonus points** - Some competitions add bonus points not visible in score columns?
4. **Parser bugs** - Scores assigned to wrong distances?

**Task**:

1. **Extract mismatch details** from each file:
   - Run parser and capture which athletes/distances have mismatches
   - For each mismatch, record:
     - Athlete name
     - Distance label
     - Expected value (from PDF)
     - Calculated value (from parser)
     - End scores that contributed to the total

2. **Examine raw PDF data** around mismatched rows:
   - Look for patterns (e.g., all mismatches in same section, same distance, etc.)
   - Check if PDF has footnotes or annotations about scoring

3. **Focus on 1440_tulemused.pdf** (most mismatches):
   - Investigate if 1440 rounds use different half-total calculation
   - Check if half-labels (e.g., "90m+70m", "50m+30m") are assigned correctly
   - Verify end scores are being summed correctly

4. **Fix identified issues**:
   - If 1440 scoring is different, add special handling
   - If distance assignment is wrong, fix transformer logic
   - If bonus points exist, document as known limitation

5. **Test on affected files** to verify mismatch count decreases

**Expected results**:
- Understand root cause of mismatches
- Reduce mismatch count by 50%+ if fixable
- Document any unfixable mismatches (e.g., bonus points)

---

## Summary of Work Plan

### Immediate Next Steps (High Priority)
1. **Prompt 4** - Fix case-insensitive gender tokens + missing sentinels
   - **Impact**: Unlocks 6-7 files (30-35% improvement)
   - **Estimated effort**: 2-3 hours
   - **Risk**: Low - straightforward dictionary and state machine fixes

### Optional Follow-up (Medium Priority)
2. **Prompt 5** - Handle Visa-HIng multi-line format
   - **Impact**: Unlocks 1 file (5% improvement)
   - **Estimated effort**: 4-6 hours
   - **Risk**: High - requires parser refactoring
   - **Recommendation**: Consider manual processing instead

### Quality Improvements (Low Priority)
3. **Prompt 6** - Fix arithmetic mismatches
   - **Impact**: Improves data quality, no file unlocks
   - **Estimated effort**: 3-4 hours investigation + fixes
   - **Risk**: Medium - may uncover complex scoring rules

### Expected Final Results
- **After Prompt 4**: 20/20 files working (100%) OR 19/20 if Visa-HIng too complex
- **After Prompt 6**: Mismatch count < 30 total across all files
- **Overall success rate**: 95%+ of athlete records parsed correctly

---

## Notes for Implementation

1. **Test incrementally** - Don't run all 20 files after each change
2. **Git commit after each fix** - Makes it easy to rollback if issues arise
3. **Update test expectations** - Document known limitations (e.g., gender-neutral sections)
4. **Consider manual fallbacks** - Some formats may not be worth automating
5. **Performance**: All fixes should maintain current parsing speed (~1 file/second)
