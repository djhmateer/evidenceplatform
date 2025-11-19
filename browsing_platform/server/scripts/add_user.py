import sys
from pathlib import Path

# DM 18th Nov Add project root to Python path
# also added blank __init__.py to lots of places 

# You can keep package-mode = false since this is an internal application. This approach is simpler than full
# package mode and works well for server applications that won't be distributed.
# Each standalone script needs the sys.path boilerplate. But for a server
#   application with a handful of scripts,
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from browsing_platform.server.services.user_manager import insert_user, User


if __name__ == "__main__":
    email = input("Enter user email: ")
    password = input("Enter new password (12 characters or more): ")
    if len(password) < 12:
        print("Password must be at least 12 characters long")
    user = insert_user(User(
        email=email,
        password_to_set=password,
        admin=True,
    ))