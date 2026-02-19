"""
RBL Credit Card Statement Parser.
Format: Date | Transaction Details | Merchant Category | Amount DR/CR
"""
import pdfplumber
import re


def parse_rbl_credit(filepath, password=None):
    """Parse RBL Credit Card statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            _process_rbl_credit_text(text, transactions)

    return transactions


def _process_rbl_credit_text(text, transactions):
    """Process RBL credit card statement from text."""
    lines = text.split('\n')

    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}-\d{1,2}-\d{4}|\d{1,2}\s+\w{3}\s+\d{2,4})')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})\s*(DR|CR|Dr|Cr)?\s*$')

    in_transactions = False
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()

        # Detect transaction section
        if any(kw in lower for kw in ['transaction detail', 'domestic transaction', 
                                       'international transaction', 'purchases & cash']):
            in_transactions = True
            continue

        # End of section
        if any(kw in lower for kw in ['important message', 'how to make payment',
                                       'closest indusind', 'marketing message',
                                       'promotional message', 'total']):
            if current_txn:
                _finalize_txn(current_txn, transactions)
                current_txn = None
            in_transactions = False
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
                _finalize_txn(current_txn, transactions)

            date_str = date_match.group(1)
            rest = line[date_match.end():].strip()

            amt_match = amount_pattern.search(rest)
            amount = ''
            dr_cr = ''
            if amt_match:
                amount = amt_match.group(1)
                dr_cr = (amt_match.group(2) or '').upper()
                rest = rest[:amt_match.start()].strip()

            current_txn = {
                'date': date_str,
                'description': rest,
                'amount': amount,
                'dr_cr': dr_cr,
            }
        elif current_txn:
            amt_match = amount_pattern.search(line)
            if amt_match and not current_txn['amount']:
                current_txn['amount'] = amt_match.group(1)
                current_txn['dr_cr'] = (amt_match.group(2) or '').upper()
                desc_part = line[:amt_match.start()].strip()
                if desc_part:
                    current_txn['description'] += ' ' + desc_part
            elif not any(kw in line.lower() for kw in ['page', 'statement', 'card no']):
                current_txn['description'] += ' ' + line

    if current_txn:
        _finalize_txn(current_txn, transactions)


def _finalize_txn(txn, transactions):
    if not txn.get('amount') or not txn.get('date'):
        return

    amount = txn['amount'].replace(',', '')
    try:
        amount_float = float(amount)
    except ValueError:
        return

    if amount_float == 0:
        return

    desc = re.sub(r'\s+', ' ', txn['description']).strip()

    if txn['dr_cr'] == 'CR' or 'PAYMENT' in desc.upper():
        debit = ''
        credit = amount_float
    else:
        debit = amount_float
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
    if any(kw in desc for kw in ['ZOMATO', 'SWIGGY', 'FOOD', 'RESTAURANT']):
        return 'Food & Dining'
    if any(kw in desc for kw in ['AMAZON', 'FLIPKART']):
        return 'Shopping Online'
    if any(kw in desc for kw in ['PETROL', 'FUEL']):
        return 'Fuel'
    if any(kw in desc for kw in ['PAYMENT', 'REVERSAL', 'REFUND']):
        return 'Payment/Refund'
    if any(kw in desc for kw in ['FEE', 'CHARGE', 'GST']):
        return 'Fees & Charges'
    if any(kw in desc for kw in ['EMI', 'LOAN']):
        return 'EMI/Loan'
    return 'General'
