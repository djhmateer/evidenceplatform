import os
import subprocess
import sys
from typing import Optional


# Determine if we're running in a PyInstaller bundle
def is_bundled():
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def has_uncommitted_changes():
    """Check for uncommitted git changes in the current directory."""
    try:
        # Check if there are any staged but uncommitted changes
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if result.returncode != 0:
            return True

        # Check if there are any unstaged changes
        result = subprocess.run(
            ["git", "diff", "--quiet"],
            capture_output=True,
        )
        if result.returncode != 0:
            return True

        # Check for untracked files
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip():
            return True

        return False
    except FileNotFoundError:
        print("Git is not installed or not available in the PATH.")
        return True


def get_current_commit_id() -> Optional[str]:
    if is_bundled():
        # When running as executable, use the pre-stored commit ID
        commit_file = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'commit_id.txt')
        try:
            with open(commit_file, 'r') as f:
                return f.read().strip()
        except:
            return "unknown-bundled"
    """Get the commit ID of the current HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print("Error: Unable to retrieve the current commit ID. Is this a git repository?")
        return None
    except FileNotFoundError:
        print("Git is not installed or not available in the PATH.")
        return None

def get_github_permalink() -> Optional[str]:
    commit_id = get_current_commit_id()
    if commit_id is None:
        commit_id = "main"
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
        remote_url = result.stdout.strip()
        if remote_url.endswith('.git'):
            remote_url = remote_url[:-4]
        remote_url += f"/tree/{commit_id}"
        print(remote_url)
        return remote_url
    except:
        print("Error: Unable to retrieve the remote origin URL.")
        return None

def ensure_committed() -> str:
    if (not is_bundled()) and has_uncommitted_changes():
        proceed_despite_uncommited_changes = (input("You have may have uncommitted changes. Are you sure you want to proceed? (yes/no): ")
                    .strip().lower())
        if proceed_despite_uncommited_changes not in {"yes", "y"}:
            print("Exiting...")
            sys.exit(0)
    print("Proceeding with execution...")
    commit_id = get_current_commit_id()
    print(f"Commit ID: {commit_id}")
    return commit_id


if __name__ == "__main__":
    get_github_permalink()