import os
import sys

# Same approach as the other tests: put researchAgent/ on the path so `research` imports.
# tests/security/ -> tests/ -> researchAgent/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
