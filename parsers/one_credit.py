"""
One Credit Card Statement Parser.
Format: Date | Merchant Name | Transaction Type | Reward Points | Amount (Rupees)
"""
import pdfplumber
import re


def parse_one_credit(filepath, password=None):
    """Parse One Credit Card statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            _process_text(text, transactions)

    return transactions


def _process_text(text, transactions):
    """Process One Credit Card statement."""
    lines = text.split('\n')

    date_pattern = re.compile(r'^(\d{1,2}\s+\w{3})')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})')

    in_transactions = False
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()

        if 'transaction history' in lower:
            in_transactions = True
            continue

        if any(kw in lower for kw in ['date', 'merchant name', 'transaction']) and 'reward' in lower:
            continue  # Header row

        if any(kw in lower for kw in ['total spends', 'total repayments', 'rewards summary',
                                       'interest charged', 'contact us', 'note:', 'important',
                                       'page ', 'fee summary']):
            if current_txn:
                _finalize(current_txn, transactions)
                current_txn = None
            continue

        if not in_transactions:
            date_match = date_pattern.match(line)
            if date_match and amount_pattern.search(line):
                in_transactions = True
            else:
                continue

        date_match = date_pattern.match(line)
        if date_match:
            if current_txn:
                _finalize(current_txn, transactions)

            date_str = date_match.group(1)
            rest = line[date_match.end():].strip()

            # Find amounts
            amounts = amount_pattern.findall(rest)
            desc = rest
            for amt in amounts:
                desc = desc.replace(amt, '', 1)
            desc = re.sub(r'\s+', ' ', desc).strip()
            # Remove reward points (small numbers) and transaction type
            desc = re.sub(r'\b\d{1,2}\.\d{2}\b', '', desc)  # Small reward points
            desc = re.sub(r'\s+(TOKEN_ECOM|POS|ECOM|ATM|CONTACTLESS)\s*', ' ', desc, flags=re.IGNORECASE)
            desc = re.sub(r'\s+', ' ', desc).strip()

            amount = float(amounts[-1].replace(',', '')) if amounts else 0

            current_txn = {
                'date': date_str,
                'description': desc,
                'amount': amount,
                'raw_line': line
            }
        elif current_txn:
            # Continuation
            amounts = amount_pattern.findall(line)
            if amounts and not current_txn.get('amount'):
                current_txn['amount'] = float(amounts[-1].replace(',', ''))
            cleaned = line
            for amt in amounts:
                cleaned = cleaned.replace(amt, '').strip()
            if cleaned and not re.match(r'^\d+\.?\d*$', cleaned):
                current_txn['description'] += ' ' + cleaned

    if current_txn:
        _finalize(current_txn, transactions)


def _finalize(txn, transactions):
    amount = txn.get('amount', 0)
    if amount == 0:
        return

    desc = re.sub(r'\s+', ' ', txn['description']).strip()
    if not desc:
        return

    # One Card: negative amounts or specific keywords = credit
    raw = txn.get('raw_line', '')
    is_credit = '-' in raw.split(desc)[-1] if desc else False
    
    if any(kw in desc.upper() for kw in ['REFUND', 'REVERSAL', 'CASHBACK', 'REPAYMENT']):
        is_credit = True

    # Check for negative/credit indicator
    if '(' in raw and ')' in raw:  # Amounts in parentheses
        is_credit = True

    if is_credit:
        debit = ''
        credit = amount
    else:
        debit = amount
        credit = ''

    transactions.append({
        'date': txn['date'],
        'description': desc,
        'debit': debit,
        'credit': credit,
        'balance': '',
        'ledger': _determine_ledger(desc)
    })


def _determine_ledger(description):
    desc = description.upper()
    if any(kw in desc for kw in ['ZOMATO', 'SWIGGY', 'FOOD']):
        return 'Food & Dining'
    if any(kw in desc for kw in ['BLINKIT', 'GROCERY', 'ZEPTO', 'BIGBASKET']):
        return 'Groceries'
    if any(kw in desc for kw in ['AMAZON', 'FLIPKART', 'MYNTRA']):
        return 'Shopping Online'
    if any(kw in desc for kw in ['NETFLIX', 'SPOTIFY']):
        return 'Entertainment'
    if any(kw in desc for kw in ['UBER', 'OLA', 'RAPIDO']):
        return 'Transport'
    if any(kw in desc for kw in ['PAYMENT', 'REFUND']):
        return 'Payment/Refund'
    return 'General'
