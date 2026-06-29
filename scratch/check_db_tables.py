import os
import django
import sys

sys.path.append('c:/Users/Ashish/Downloads/10_6/django/padosi_agent')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'padosi_agent.settings')
django.setup()

from django.db import connection

def test():
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        print("Tables in database:", tables)
        
        for table in ['agents', 'auth_user', 'users', 'agent_profiles']:
            if table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                count = cursor.fetchone()[0]
                print(f"Row count in {table}:", count)
            else:
                print(f"Table {table} does not exist")
                
        # Let's inspect some user IDs in agents
        cursor.execute("SELECT id, user_id, fullname, status FROM agents LIMIT 5")
        print("First 5 agents:")
        for row in cursor.fetchall():
            print(row)
            
        # Let's inspect users in auth_user
        cursor.execute("SELECT id, username, email FROM auth_user LIMIT 5")
        print("First 5 auth_users:")
        for row in cursor.fetchall():
            print(row)

if __name__ == '__main__':
    test()
