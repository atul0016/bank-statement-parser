"""
Standard Chartered Bank Account Statement Parser.
Format: Date | Value Date | Description | Cheque | Deposit | Withdrawal | Balance
"""
import pdfplumber
import re


def parse_standard_bank(filepath, password=None):
    """Parse Standard Chartered Bank account statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            # Default extraction gives reliable 7-column layout
            tables = page.extract_tables()

            if tables:
                for table in tables:
                    _process_table(table, transactions)
            else:
                text = page.extract_text() or ''
                _process_text(text, transactions)

    return transactions


def _process_table(table, transactions):
    """Process Standard Chartered table with column-aware extraction.
    
    Columns: [0]Date | [1]Value Date | [2]Description | [3]Cheque | [4]Deposit | [5]Withdrawal | [6]Balance
    """
    # Detect column positions from header
    col_deposit = 4
    col_withdrawal = 5
    col_balance = 6
    col_desc = 2
    
    for row in table:
        if not row or len(row) < 3:
            continue

        cells = [str(c).strip() if c else '' for c in row]
        combined = ' '.join(cells).lower()

        # Detect header row to get actual column positions
        if 'deposit' in combined or 'withdrawal' in combined:
            for i, c in enumerate(cells):
                cl = c.lower().strip()
                if 'deposit' in cl:
                    col_deposit = i
                elif 'withdrawal' in cl:
                    col_withdrawal = i
                elif 'balance' in cl:
                    col_balance = i
                elif 'description' in cl:
                    col_desc = i
            continue

        # Skip header/summary rows
        if any(kw in combined for kw in ['date', 'value', 'cheque', 'total']):
            if not re.match(r'\d{1,2}\s+\w{3}\s+\d{4}', cells[0]):
                continue

        # Look for date in first cell
        date_match = re.match(r'(\d{1,2}\s+\w{3}\s+\d{4})', cells[0])
        if not date_match:
            # Continuation row
            if transactions and cells[col_desc] if col_desc < len(cells) else '':
                extra = cells[col_desc].strip() if col_desc < len(cells) else ''
                if extra:
                    transactions[-1]['description'] += ' ' + extra
            continue

        date_str = date_match.group(1)
        description = cells[col_desc].strip() if col_desc < len(cells) else ''
        description = re.sub(r'\s+', ' ', description).strip()

        # Get deposit (credit), withdrawal (debit), balance by column
        credit = ''
        if col_deposit < len(cells) and cells[col_deposit].strip():
            val = cells[col_deposit].replace(',', '').strip()
            if re.match(r'^[\d.]+$', val):
                credit = cells[col_deposit].strip()

        debit = ''
        if col_withdrawal < len(cells) and cells[col_withdrawal].strip():
            val = cells[col_withdrawal].replace(',', '').strip()
            if re.match(r'^[\d.]+$', val):
                debit = cells[col_withdrawal].strip()

        balance = ''
        if col_balance < len(cells) and cells[col_balance].strip():
            val = cells[col_balance].replace(',', '').strip()
            if re.match(r'^[\d.]+$', val):
                balance = cells[col_balance].strip()

        # Skip "BALANCE FORWARD" row if no debit/credit
        if 'BALANCE FORWARD' in description.upper() and not debit and not credit:
            if balance:
                transactions.append({
                    'date': date_str,
                    'description': description,
                    'debit': '',
                    'credit': '',
                    'balance': balance,
                    'ledger': 'Opening Balance'
                })
            continue

        if description:
            transactions.append({
                'date': date_str,
                'description': description,
                'debit': debit,
                'credit': credit,
                'balance': balance,
                'ledger': _determine_ledger(description)
            })


def _process_text(text, transactions):
    lines = text.split('\n')
    date_pattern = re.compile(r'^(\d{1,2}\s+\w{3}\s+\d{4})')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})')
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()
        if any(kw in lower for kw in ['branch', 'statement date', 'currency', 'account type',
                                       'account no', 'nominee', 'branch address', 'page ']):
            continue

        date_match = date_pattern.match(line)
        if date_match:
            if current_txn:
                transactions.append(current_txn)

            date_str = date_match.group(1)
            rest = line[date_match.end():].strip()

            # Remove value date
            val_match = date_pattern.match(rest)
            if val_match:
                rest = rest[val_match.end():].strip()

            amounts = amount_pattern.findall(rest)
            desc = rest
            for amt in amounts:
                desc = desc.replace(amt, '', 1)
            desc = re.sub(r'\s+', ' ', desc).strip()

            float_amounts = [float(a.replace(',', '')) for a in amounts]

            debit = ''
            credit = ''
            balance = ''

            if 'BALANCE FORWARD' in desc.upper():
                balance = float_amounts[-1] if float_amounts else ''
            elif len(float_amounts) >= 3:
                credit = float_amounts[-3] if float_amounts[-3] > 0 else ''
                debit = float_amounts[-2] if float_amounts[-2] > 0 else ''
                balance = float_amounts[-1]
            elif len(float_amounts) == 2:
                balance = float_amounts[-1]
                debit = float_amounts[0]
            elif len(float_amounts) == 1:
                balance = float_amounts[0]

            current_txn = {
                'date': date_str,
                'description': desc,
                'debit': debit,
                'credit': credit,
                'balance': balance,
                'ledger': _determine_ledger(desc)
            }
        elif current_txn:
            amounts = amount_pattern.findall(line)
            cleaned = line
            for amt in amounts:
                cleaned = cleaned.replace(amt, '').strip()
            if cleaned and not re.match(r'^[\d\s,.]+$', cleaned):
                current_txn['description'] += ' ' + cleaned

    if current_txn:
        transactions.append(current_txn)


def _determine_ledger(description):
    desc = description.upper()
    if any(kw in desc for kw in ['UPI', 'IMPS', 'NEFT', 'RTGS']):
        if any(kw in desc for kw in ['SWIGGY', 'ZOMATO']):
            return 'Food & Dining'
        return 'Transfer'
    if 'SALARY' in desc:
        return 'Salary'
    if 'INTEREST' in desc:
        return 'Interest'
    if 'BALANCE FORWARD' in desc:
        return 'Opening Balance'
    return 'General'
