#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os # It allows us to interact with the operating system. 
import sys #  It allows us to run Django commands from the command line. 

# This is the main function that will be called when the script is run.
def main():
    """Run administrative tasks."""
    # This is the environment variable that will be set if the import is successful.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
    # This is the try block that will be executed if the import is successful.
    try:
        # This is the import statement that will be executed if the import is successful.
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # This is the except block that will be executed if the import is not successful.
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # This is the execute_from_command_line function that will be called if the import is successful.
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
