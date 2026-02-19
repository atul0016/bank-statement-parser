"""
IndusInd Credit Card Statement Parser.
Format: Date | Transaction Details | Merchant Category | Amount DR
"""
import pdfplumber
import re


def parse_indusind_credit(filepath, password=None):
    """Parse IndusInd Credit Card statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            _process_text(text, transactions)

    return transactions


def _process_text(text, transactions):
    """Process IndusInd credit card statement."""
    lines = text.split('\n')

    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})\s*(DR|CR|Dr|Cr)?\s*$')

    in_transactions = False
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()

        if 'purchases & cash' in lower or 'transaction detail' in lower:
            in_transactions = True
            continue

        if any(kw in lower for kw in ['marketing message', 'how to make payment',
                                       'closest indusind', 'important message',
                                       'use convenient', 'use your tpin',
                                       'total', 'previous balance']):
            if current_txn:
                _finalize(current_txn, transactions)
                current_txn = None
            continue

        date_match = date_pattern.match(line)
        if date_match:
            in_transactions = True
            if current_txn:
                _finalize(current_txn, transactions)

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
        elif current_txn and in_transactions:
            amt_match = amount_pattern.search(line)
            if amt_match and not current_txn['amount']:
                current_txn['amount'] = amt_match.group(1)
                current_txn['dr_cr'] = (amt_match.group(2) or '').upper()
                desc_part = line[:amt_match.start()].strip()
                if desc_part:
                    current_txn['description'] += ' ' + desc_part
            elif not any(kw in line.lower() for kw in ['page', 'statement']):
                # Check for merchant category codes (3-digit numbers)
                if not re.match(r'^\d{3}$', line):
                    current_txn['description'] += ' ' + line

    if current_txn:
        _finalize(current_txn, transactions)


def _finalize(txn, transactions):
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
    # Remove merchant category codes at end
    desc = re.sub(r'\s+\d{3}\s*$', '', desc)

    if txn['dr_cr'] == 'CR' or 'PAYMENT' in desc.upper() or 'CREDIT' in desc.upper():
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
    if any(kw in desc for kw in ['RESTAURANT', 'FOOD', 'SWEETS', 'CAFE']):
        return 'Food & Dining'
    if any(kw in desc for kw in ['PERSONAL CARE']):
        return 'Personal Care'
    if any(kw in desc for kw in ['PAYMENT', 'REFUND']):
        return 'Payment/Refund'
    if any(kw in desc for kw in ['FEE', 'CHARGE', 'GST']):
        return 'Fees & Charges'
    return 'General'
