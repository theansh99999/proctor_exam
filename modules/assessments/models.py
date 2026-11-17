"""
modules/assessments/models.py
-----------------------------
Assessment entity re-exports from central models.
Assessment maps directly to Exam with multi-purpose assessment extensions.
"""
import models

Assessment = models.Exam
