"""
Category mapping utility to convert backend classifications to UI categories
"""
import logging

logger = logging.getLogger(__name__)

# UI Categories
UI_CATEGORIES = [
    'All',
    'Invoice',
    'Payment',
    'Contracts',
    'Sales',
    'Purchase',
    'ID / Passport',
    'Tenancy Contract',
    'Unknown'
]

def map_backend_to_ui_category(backend_classification: str | None) -> str:
    """
    Map backend classification to UI category
    
    Args:
        backend_classification: Backend classification string (e.g., "Invoice", "Contracts", "Tenancy Contract")
        
    Returns:
        UI category string (e.g., "Invoice", "Contracts", "Tenancy Contract")
    """
    if not backend_classification:
        return 'Unknown'
    
    classification = backend_classification.lower().strip()
    
    # Direct mappings for specific contract types
    if 'tenancy contract' in classification or 'rental' in classification or 'lease' in classification:
        return 'Tenancy Contract'
    
    if 'sales & purchase agreement' in classification or 'spa' in classification:
        return 'Contracts'
    
    if 'broker agreement' in classification:
        return 'Contracts'
    
    if 'property management contract' in classification:
        return 'Contracts'
    
    if 'renewal contract' in classification:
        return 'Contracts'
    
    if 'refund' in classification and 'cancellation' in classification:
        return 'Contracts'
    
    # General contract mappings
    if 'contract' in classification or 'agreement' in classification:
        return 'Contracts'
    
    # Invoice and Payment mappings
    if 'invoice' in classification:
        return 'Invoice'
    
    if 'payment' in classification:
        return 'Payment'
    
    if 'receipt' in classification or 'voucher' in classification:
        return 'Payment'
    
    # Sales and Purchase mappings
    if 'sales' in classification and 'purchase' not in classification:
        return 'Sales'
    
    if 'purchase' in classification:
        return 'Purchase'
    
    # ID/Passport mappings
    if 'id' in classification or 'passport' in classification:
        return 'ID / Passport'
    
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

