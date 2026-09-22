import sys
import os
import pytest

# Ensure Funpay AutoSteam is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Funpay AutoSteam")))

from FunPayAPI import Account
from FunPayAPI.types import SubCategory, Category, SubCategoryTypes

@pytest.fixture
def dummy_account():
    """Creates an uninitiated Account instance for testing."""
    return Account("test_golden_key_12345", user_agent="TestAgent/1.0")

@pytest.fixture
def initiated_account():
    """Creates an Account instance in initiated state with mock profile data."""
    acc = Account("test_golden_key_12345", user_agent="TestAgent/1.0")
    acc._Account__initiated = True
    acc.id = 123456
    acc.username = "TestSeller"
    acc.csrf_token = "mock_csrf_token_abcdef"
    acc.phpsessid = "mock_phpsessid_123"
    
    # Mock category & subcategory
    cat = Category(10, "Steam", {})
    subcat = SubCategory(1086, "Steam Balance", SubCategoryTypes.COMMON, cat)
    acc._Account__sorted_subcategories[SubCategoryTypes.COMMON][1086] = subcat
    return acc
