"""
Category mapping utility to convert backend classifications to UI categories
"""
import logging

logger = logging.getLogger(__name__)

# UI Categories
UI_CATEGORIES = [
    'All',
    'Contracts',
    'Invoices',
    'Insurance',
    'RTA',
    'Forms',
    'ID / Passport',
    'Others',
    'Unknown'
]

def map_backend_to_ui_category(backend_classification: str | None) -> str:
    """
    Map backend classification to UI category
    
    Args:
        backend_classification: Backend classification string (e.g., "Invoice", "Contract/Agreement")
        
    Returns:
        UI category string (e.g., "Invoices", "Contracts")
    """
    if not backend_classification:
        return 'Unknown'
    
    classification = backend_classification.lower().strip()
    
    # Direct mappings
    if 'contract' in classification or 'agreement' in classification:
        return 'Contracts'
    
    if 'invoice' in classification:
        return 'Invoices'
    
    if 'receipt' in classification or 'voucher' in classification:
        return 'Invoices'
    
    if 'insurance' in classification:
        return 'Insurance'
    
    if 'rta' in classification or 'real estate' in classification or 'property' in classification:
        return 'RTA'
    
    if 'form' in classification or 'legal document' in classification:
        return 'Forms'
    
    if 'id' in classification or 'passport' in classification:
        return 'ID / Passport'
    
    if 'other' in classification or classification == 'other':
        return 'Others'
    
    # Check if it matches any UI category directly (case-insensitive)
    for ui_category in UI_CATEGORIES:
        if ui_category.lower() == classification or classification in ui_category.lower():
            return ui_category
    
    return 'Unknown'

def get_all_ui_categories() -> list[str]:
    """Get list of all UI categories"""
    return UI_CATEGORIES.copy()

def is_valid_ui_category(category: str) -> bool:
    """Check if a category is a valid UI category"""
    return category in UI_CATEGORIES

