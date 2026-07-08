from pathlib import Path
from django.conf import settings

def get_invoice_root():
    """
    Returns the absolute base path for invoice storage: media/app/private/invoices/
    """
    base_dir = getattr(settings, 'BASE_DIR', Path(__file__).resolve().parent.parent.parent.parent)
    return base_dir / 'media' / 'app' / 'private' / 'invoices'

def get_folder_path(folder_name):
    """
    Returns the absolute path for a specific discount folder.
    """
    return get_invoice_root() / folder_name

def ensure_invoice_directories():
    """
    Ensures that the expected folder structure exists.
    """
    folders = [
        'no_discount',
        '10_percent',
        '25_percent',
        '50_percent',
        '1re',
        'others'
    ]
    
    root_dir = get_invoice_root()
    root_dir.mkdir(parents=True, exist_ok=True)
    
    for folder in folders:
        folder_path = get_folder_path(folder)
        folder_path.mkdir(parents=True, exist_ok=True)
