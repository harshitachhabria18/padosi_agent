import pandas as pd
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Import blacklisted agents from IRDAI Excel file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            default='data/blacklisted_agents.xlsx',
            help='Path to Excel file'
        )
        parser.add_argument(
            '--source',
            type=str,
            default='manual',
            choices=['manual', 'auto'],
            help='manual = IRDAI downloaded Excel (header on row 2), auto = script generated Excel (header on row 1)'
        )

    def handle(self, *args, **options):
        file_path = options['file']
        self.stdout.write(f'Reading: {file_path}')

        header_row = 1 if options['source'] == 'manual' else 0
        df = pd.read_excel(file_path, header=header_row, engine='openpyxl')

        self.stdout.write(f'Columns found: {list(df.columns)}')
        self.stdout.write(f'Total rows: {len(df)}')

        # Clean column names
        df.columns = df.columns.str.strip()

        inserted = 0
        skipped = 0
        errors = 0

        with connection.cursor() as cursor:
            for index, row in df.iterrows():
                try:
                    agent_name = str(row.get('Agent Name', '') or '').strip()
                    if not agent_name or agent_name == 'nan':
                        skipped += 1
                        continue

                    sr_no = row.get('SR.NO')
                    insurer = str(row.get('Insurer', '') or '').strip()
                    insurer_type = str(row.get('Insurer type', '') or '').strip()
                    pan = str(row.get('PAN', '') or '').strip()
                    agency_code = str(row.get('Agency Code', '') or '').strip()

                    # Parse date
                    raw_date = row.get('Blacklisted date')
                    blacklisted_date = None
                    if pd.notna(raw_date):
                        try:
                            if isinstance(raw_date, datetime):
                                blacklisted_date = raw_date.date()
                            else:
                                blacklisted_date = pd.to_datetime(
                                    str(raw_date)
                                ).date()
                        except Exception:
                            blacklisted_date = None

                    # Insert new rows only — skip duplicates silently
                    cursor.execute("""
                        INSERT IGNORE INTO blacklisted_agents
                            (sr_no, insurer, insurer_type, pan,
                             agent_name, agency_code, blacklisted_date, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, [
                        int(sr_no) if pd.notna(sr_no) else None,
                        insurer or None,
                        insurer_type or None,
                        pan or None,
                        agent_name,
                        agency_code or None,
                        blacklisted_date,
                        'IRDAI'
                    ])

                    if cursor.rowcount == 1:
                        inserted += 1
                    else:
                        skipped += 1

                    if (index + 1) % 1000 == 0:
                        self.stdout.write(f'Processed {index + 1} rows...')

                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        self.stdout.write(
                            self.style.WARNING(f'Row {index} error: {e}')
                        )

        self.stdout.write(self.style.SUCCESS(
            f'\nImport complete!'
            f'\n  Inserted: {inserted}'
            f'\n  Skipped:  {skipped}'
            f'\n  Errors:   {errors}'
        ))
