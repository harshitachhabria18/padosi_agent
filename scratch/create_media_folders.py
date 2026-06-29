import os
from django.conf import settings
import django

# Setup Django environment
sys_path = 'c:/Users/Ashish/Downloads/10_6/django/padosi_agent'
import sys
if sys_path not in sys.path:
    sys.path.append(sys_path)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

def create_structure():
    media_root = settings.MEDIA_ROOT
    print("MEDIA_ROOT is:", media_root)
    
    subdirs = [
        'logs',
        'app',
        'app/private',
        'app/private/invoices',
        'app/private/invoices/discount',
        'app/private/invoices/nodiscount',
        'app/private/pincode_imports',
        'app/public',
        'app/public/achievement',
        'app/public/profile'
    ]
    
    for subdir in subdirs:
        dir_path = os.path.join(media_root, subdir)
        os.makedirs(dir_path, exist_ok=True)
        print(f"Verified directory exists: {dir_path}")
        
    print("Folder structure successfully created!")

if __name__ == '__main__':
    create_structure()
