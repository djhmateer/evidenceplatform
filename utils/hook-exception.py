# hook-exception.py
import sys
from traceback import format_exception

def exception_hook(exctype, value, traceback):
    # Print the error and traceback
    print(''.join(format_exception(exctype, value, traceback)))
    print("\nAn error occurred. Press Enter to exit...")
    input()  # Wait for user input before closing

# Install the custom exception handler
sys.excepthook = exception_hook