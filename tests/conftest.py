"""
Shared pytest fixtures for the EPISTEME test suite.
"""
import os
import sys

# Ensure the project root is on the path so 'episteme' is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
