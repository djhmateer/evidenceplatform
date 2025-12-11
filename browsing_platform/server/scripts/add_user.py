import sys
from pathlib import Path

# Add project root to path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from browsing_platform.server.services.user_manager import insert_user, User


if __name__ == "__main__":
    email = input("Enter user email: ")
    password = input("Enter new password (12 characters or more): ")
    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters long")
    user = insert_user(User(
        email=email,
        password_to_set=password,
        admin=True,
    ))