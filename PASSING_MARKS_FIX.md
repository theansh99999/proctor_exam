# Fix 7: PASSING MARKS - VALIDATION & SEMANTIC CLARIFICATION

## Issue
The `passing_marks` field had multiple problems:
1. **Ambiguous semantics** - Unclear if it was raw marks or percentage
2. **No validation** - Teachers could set invalid values (negative, exceeding total marks)
3. **No constraints** - No enforcement that `passing_marks <= total_possible_marks`
4. **Confusion risk** - Could lead to invalid pass/fail results

## Real Solution Implemented

### 1. **Semantic Documentation** (models.py)
```python
# IMPORTANT: passing_marks is stored as RAW MARKS, not percentage
# Example: For 100 total marks exam, passing_marks=40 means 40/100 marks (40% cut-off)
# Comparison: if submission.score >= exam.passing_marks: student_passed = True
passing_marks = Column(Float, default=0.0)
```

### 2. **Pydantic Field Validators** (routers/teacher_r.py)
Added validators to both `ExamCreateAPI` and `ExamEditAPI` schemas:

```python
@field_validator('passing_marks')
@classmethod
def validate_passing_marks_range(cls, v):
    """Validate that passing_marks is not negative and is reasonable"""
    if v < 0:
        raise ValueError(f"passing_marks cannot be negative, got {v}")
    if v > 10000:  # Sanity check - no exam will have 10000 marks
        raise ValueError(f"passing_marks seems too high ({v}), maximum 10000 allowed")
    return v

def calculate_max_marks(self) -> float:
    """Calculate total possible marks for this exam"""
    total = 0.0
    for question in self.questions:
        marks = question.marks if question.marks is not None else self.default_marks
        total += marks
    return total
```

### 3. **Runtime Validation in Endpoints** (routers/teacher_r.py)
Added validation checks in both exam creation and editing:

#### In `api_create_exam()`:
```python
# Validate that passing_marks <= total possible marks
max_marks = exam_data.calculate_max_marks()
if exam_data.passing_marks > max_marks:
    raise HTTPException(
        status_code=400, 
        detail=f"passing_marks ({exam_data.passing_marks}) cannot exceed total possible marks ({max_marks})"
    )
```

#### In `api_edit_exam()`:
```python
# Validate that passing_marks <= total possible marks
max_marks = exam_data.calculate_max_marks()
if exam_data.passing_marks > max_marks:
    raise HTTPException(
        status_code=400, 
        detail=f"passing_marks ({exam_data.passing_marks}) cannot exceed total possible marks ({max_marks})"
    )
```

### 4. **Code Comments at All Comparisons**
Added clarifying comments at all pass/fail logic locations showing that:
- `passing_marks` is **RAW MARKS** (not percentage)
- Compared directly with `submission.score` (also raw marks)

## Validation Tests ✅

All validators tested and **PASSING**:

```
Test 1: Negative passing_marks
  ✅ PASSED - Correctly rejected: passing_marks cannot be negative

Test 2: Passing_marks > 10000
  ✅ PASSED - Correctly rejected: passing_marks seems too high

Test 3: Valid passing_marks  
  ✅ PASSED - Created exam with passing_marks=5, max_marks=10.0

Test 4: calculate_max_marks()
  ✅ PASSED - calculate_max_marks() = 31.0 (with 3 questions)
```

## Example Scenarios

### Scenario A: Valid 100-mark exam with 40% passing threshold
```json
{
  "questions": [
    {"marks": 10},    // 10 marks
    {"marks": 20},    // 20 marks
    {"marks": 70}     // 70 marks
  ],                  // Total = 100 marks
  "passing_marks": 40 // 40 out of 100 (40% cut-off)
}
```
✅ **Accepted** - passing_marks (40) ≤ total marks (100)

### Scenario B: Invalid - passing_marks exceeds total marks
```json
{
  "questions": [
    {"marks": 10},
    {"marks": 15}
  ],                  // Total = 25 marks
  "passing_marks": 50 // INVALID - exceeds total!
}
```
❌ **Rejected** - Error: "passing_marks (50) cannot exceed total possible marks (25)"

### Scenario C: Invalid - Negative passing_marks
```json
{
  "questions": [...],
  "passing_marks": -10 // INVALID - cannot be negative
}
```
❌ **Rejected** - Error: "passing_marks cannot be negative, got -10"

## Files Modified

1. **models.py**
   - Added 3-line docstring to `passing_marks` column clarifying it's raw marks

2. **routers/teacher_r.py**
   - Added `field_validator` to `ExamCreateAPI` for range validation
   - Added `field_validator` to `ExamEditAPI` for range validation  
   - Added `calculate_max_marks()` method to compute total exam marks
   - Added validation check in `api_create_exam()` endpoint
   - Added validation check in `api_edit_exam()` endpoint
   - Added 3 clarifying code comments at pass/fail logic

3. **routers/student_r.py**
   - Added 3 clarifying comments at pass/fail comparisons

## Protection Coverage

✅ **Schema Validation** - Rejects negative or unreasonably high values  
✅ **Business Logic Validation** - Ensures passing_marks ≤ total exam marks  
✅ **Semantic Documentation** - Clear comment explaining it's RAW MARKS  
✅ **API Error Messages** - Clear, actionable error responses to teachers  
✅ **Code Comments** - Reinforces semantics at all comparison points

## Why This Actually Fixes It

- **Before**: Teacher could set passing_marks=50 for 20-mark exam → Student with 15 marks passes? Bug!
- **After**: API rejects with: "passing_marks (50) cannot exceed total possible marks (20)" → Clear error message

This prevents the ambiguity from causing real bugs in production.
