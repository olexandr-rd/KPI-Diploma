# Create a simple debug script to check the restore process:
# Save as debug_restore.py

import os
import re
from pathlib import Path


def analyze_backup_file(backup_file):
    """Analyze a backup file to see what data it contains for monitoring_energylog"""

    print(f"Analyzing backup file: {backup_file}")
    print("-" * 50)

    try:
        with open(backup_file, 'r') as f:
            content = f.read()

        # Look for table creation
        table_pattern = r'CREATE TABLE public\.monitoring_energylog[\s\S]*?;\s*\n'
        table_match = re.search(table_pattern, content)
        if table_match:
            print("Found table creation statement")
            print(table_match.group(0)[:200] + "...")
        else:
            print("No table creation statement found")

        # Look for sequence creation
        sequence_pattern = r'CREATE SEQUENCE public\.monitoring_energylog_id_seq[\s\S]*?;\s*\n'
        sequence_match = re.search(sequence_pattern, content)
        if sequence_match:
            print("\nFound sequence creation statement")
        else:
            print("\nNo sequence creation statement found")

        # Look for data
        data_pattern = r'COPY public\.monitoring_energylog[\s\S]*?\\.\s*\n'
        data_match = re.search(data_pattern, content)
        if data_match:
            print("\nFound data COPY statement")
            data_content = data_match.group(0)
            lines = data_content.split('\n')
            data_lines = [line for line in lines if line and not line.startswith('COPY') and line != '\\.']
            print(f"Number of data rows: {len(data_lines)}")
            if data_lines:
                print(f"First data row: {data_lines[0][:100]}")
                print(f"Last data row: {data_lines[-1][:100]}")
        else:
            print("\nNo data found")

        print("-" * 50)

    except Exception as e:
        print(f"Error analyzing file: {e}")


# Usage:
if __name__ == "__main__":
    # Replace with your actual backup file path
    backup_file = "../backups/energy_data_20250503_210056.sql"
    if os.path.exists(backup_file):
        analyze_backup_file(backup_file)
    else:
        print(f"File not found: {backup_file}")