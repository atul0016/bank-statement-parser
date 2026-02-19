"""
Yes Bank Account Statement Parser.
Format: Transaction Date | Value Date | Cheque No/Reference No | Description | Withdrawals | Deposits | Running Balance
"""
import pdfplumber
import re


def parse_yes_bank(filepath, password=None):
    """Parse Yes Bank account statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            # Default extraction gives reliable 7-column layout
            tables = page.extract_tables()

            if tables:
                for table in tables:
                    _process_yes_table(table, transactions)
            
            if not transactions:
                text = page.extract_text() or ''
                _process_yes_text(text, transactions)

    return transactions


def _process_yes_table(table, transactions):
    """Process Yes Bank table with column-aware extraction.
    
    Yes Bank tables have 7 columns:
    [0] Transaction Date | [1] Value Date | [2] Cheque/Ref No |
    [3] Description | [4] Withdrawals | [5] Deposits | [6] Running Balance
    """
    # Detect column layout from header row
    col_withdrawal = 4
    col_deposit = 5
    col_balance = 6
    col_desc = 3
    
    for row in table:
        if not row or len(row) < 4:
            continue
        cells = [str(c).strip() if c else '' for c in row]
        combined = ' '.join(cells).lower()
        
        # Detect header to identify column positions
        if 'withdrawal' in combined or 'deposit' in combined:
            for i, c in enumerate(cells):
                cl = c.lower().strip()
                if 'withdrawal' in cl:
                    col_withdrawal = i
                elif 'deposit' in cl:
                    col_deposit = i
                elif 'balance' in cl and 'running' in cl or cl == 'balance':
                    col_balance = i
                elif 'description' in cl:
                    col_desc = i
            continue

        # Skip header/summary rows
        if any(kw in combined for kw in ['transaction date', 'value date', 'cheque no',
                                          'opening balance', 'closing balance',
                                          'total withdrawal', 'total deposit']):
            continue

        # Look for date in first cell
        date_match = re.match(
            r'(\d{1,2}\s+\w{3}\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})',
            cells[0]
        )
        if not date_match:
            # Continuation row → add description
            if transactions:
                extra = cells[col_desc] if col_desc < len(cells) else ''
                if extra.strip():
                    transactions[-1]['description'] += ' ' + extra.strip()
            continue

        date_str = date_match.group(1)

        # Description
        description = cells[col_desc] if col_desc < len(cells) else ''
        description = re.sub(r'\s+', ' ', description).strip()

        # Withdrawal (debit)
        debit = ''
        if col_withdrawal < len(cells) and cells[col_withdrawal].strip():
            val = cells[col_withdrawal].replace(',', '').replace(' ', '').strip()
            if val and re.match(r'^[\d.]+$', val):
                debit = cells[col_withdrawal].strip()

        # Deposit (credit)
        credit = ''
        if col_deposit < len(cells) and cells[col_deposit].strip():
            val = cells[col_deposit].replace(',', '').replace(' ', '').strip()
            if val and re.match(r'^[\d.]+$', val):
                credit = cells[col_deposit].strip()

        # Balance
        balance = ''
        if col_balance < len(cells) and cells[col_balance].strip():
            val = cells[col_balance].replace(',', '').replace(' ', '').strip()
            if val and re.match(r'^[\d.]+$', val):
                balance = cells[col_balance].strip()

        if description:
            transactions.append({
                'date': date_str,
                'description': description,
                'debit': debit,
                'credit': credit,
                'balance': balance,
                'ledger': _determine_ledger(description)
            })


def _process_yes_text(text, transactions):
    """Process Yes Bank statement from raw text."""
    lines = text.split('\n')
    date_pattern = re.compile(r'^(\d{1,2}\s+\w{3}\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})')
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()
        if any(kw in lower for kw in ['transaction date', 'value date', 'cheque no',
                                       'customer id', 'primary account', 'nominee', 'a/c opening',
                                       'account variant', 'joint holder', 'opening balance:',
                                       'total withdrawals', 'total deposits', 'closing balance:',
                                       'od limit', 'please review', 'mandatory disclaimer',
                                       'transaction codes', 'reward points']):
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

            if len(float_amounts) >= 3:
                debit = float_amounts[-3] if float_amounts[-3] > 0 else ''
                credit = float_amounts[-2] if float_amounts[-2] > 0 else ''
                balance = float_amounts[-1]
            elif len(float_amounts) == 2:
                balance = float_amounts[-1]
                if _is_debit_yes(desc):
                    debit = float_amounts[0]
                else:
                    credit = float_amounts[0]
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


def _is_debit_yes(description):
    """Check if a Yes Bank transaction is a debit."""
    desc = description.upper()
    debit_keywords = ['WITHDRAWAL', 'DEBIT', 'PAID', 'TRANSFER TO', 'FUNDS TRF TO',
                      'PURCHASE', 'POS', 'ATM', 'NACH']
    credit_keywords = ['DEPOSIT', 'CREDIT', 'RECEIVED', 'TRANSFER FROM', 'SALARY',
                       'INTEREST', 'REFUND', 'REVERSAL', 'CASHBACK']
    
    for kw in debit_keywords:
        if kw in desc:
            return True
    for kw in credit_keywords:
        if kw in desc:
            return False
    
    # UPI transactions: check From/To pattern
    if 'FROM:' in desc and 'TO:' in desc:
        return True  # Usually debit (paying someone)
    
    return True  # Default to debit


def _determine_ledger(description):
    desc = description.upper()
    if any(kw in desc for kw in ['UPI', 'IMPS', 'NEFT', 'RTGS']):
        if any(kw in desc for kw in ['ZOMATO', 'SWIGGY']):
            return 'Food & Dining'
        if any(kw in desc for kw in ['ZERODHA', 'GROWW']):
            return 'Investment'
        if any(kw in desc for kw in ['RECHARGE', 'AIRTEL', 'JIO', 'PREPAID']):
            return 'Utilities'
        if any(kw in desc for kw in ['NETFLIX', 'SPOTIFY', 'APPLE']):
            return 'Entertainment'
        if any(kw in desc for kw in ['PORTER', 'CAB', 'OLA', 'UBER']):
            return 'Transport'
        if any(kw in desc for kw in ['MEDICINE', 'BLOOD TEST', 'HOSPITAL']):
            return 'Medical'
        if 'FAMILY' in desc:
            return 'Family Transfer'
        if 'CREDIT CARD' in desc:
            return 'Credit Card Payment'
        if 'JEWELLERY' in desc:
            return 'Shopping'
        return 'Transfer'
    if 'SALARY' in desc:
        return 'Salary'
    if 'INTEREST' in desc:
        return 'Interest'
    if 'ATM' in desc or 'CASH' in desc:
        return 'Cash'
    if 'FUNDS TRF' in desc:
        return 'Transfer'
    return 'General'
