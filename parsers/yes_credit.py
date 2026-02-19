"""
Yes Credit Card Statement Parser.
Format: Date | Transaction Details | Merchant Category | Amount (Rs.) Dr/Cr
"""
import pdfplumber
import re


def parse_yes_credit(filepath, password=None):
    """Parse Yes Bank Credit Card statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            _process_yes_credit_text(text, transactions)

    return transactions


def _process_yes_credit_text(text, transactions):
    """Process Yes Credit Card statement from text."""
    lines = text.split('\n')

    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})')
    amount_pattern = re.compile(r'([\d,]+\.\d{2})\s*(Dr|Cr|DR|CR)?\.?\s*$')

    in_transactions = False
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()

        # Start of transactions
        if 'date' in lower and ('transaction detail' in lower or 'merchant category' in lower):
            in_transactions = True
            continue

        # End of transactions
        if any(kw in lower for kw in ['making only the minimum', 'presenting emi',
                                       'important message', 'promotional message',
                                       'total amount due', 'for enquiries',
                                       'please note', 'go green']):
            in_transactions = False
            continue

        if not in_transactions:
            # Also look for transaction lines even outside section
            date_match = date_pattern.match(line)
            if date_match:
                amt_match = amount_pattern.search(line)
                if amt_match:
                    in_transactions = True

        if not in_transactions:
            continue

        date_match = date_pattern.match(line)
        if date_match:
            if current_txn:
                _finalize_yes_credit_txn(current_txn, transactions)

            date_str = date_match.group(1)
            rest = line[date_match.end():].strip()

            # Check for amount at end
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
            if amt_match:
                if not current_txn['amount']:
                    current_txn['amount'] = amt_match.group(1)
                    current_txn['dr_cr'] = (amt_match.group(2) or '').upper()
                    desc_part = line[:amt_match.start()].strip()
                    if desc_part:
                        current_txn['description'] += ' ' + desc_part
            else:
                # Don't add footer/header lines
                if not any(kw in line.lower() for kw in ['page', 'statement for', 'card number']):
                    current_txn['description'] += ' ' + line

    if current_txn:
        _finalize_yes_credit_txn(current_txn, transactions)


def _finalize_yes_credit_txn(txn, transactions):
    """Finalize Yes credit card transaction."""
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
    # Remove ref numbers
    desc = re.sub(r'\s*-?\s*Ref\s*No\s*:\s*\S+', '', desc, flags=re.IGNORECASE)
    # Remove merchant category codes  
    desc = re.sub(r'\s*\d{3,4}\s*$', '', desc)

    if 'PAYMENT RECEIVED' in desc.upper() or txn['dr_cr'] == 'CR':
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
    if any(kw in desc for kw in ['AMAZON', 'FLIPKART', 'MYNTRA']):
        return 'Shopping Online'
    if any(kw in desc for kw in ['PETROL', 'FUEL', 'AUTO FILLS']):
        return 'Fuel'
    if any(kw in desc for kw in ['BLINKIT', 'ZEPTO', 'GROCERY', 'DMART', 'BIGBASKET']):
        return 'Groceries'
    if any(kw in desc for kw in ['NETFLIX', 'SPOTIFY', 'HOTSTAR']):
        return 'Entertainment'
    if any(kw in desc for kw in ['RECHARGE', 'AIRTEL', 'JIO', 'ELECTRICITY']):
        return 'Utilities'
    if any(kw in desc for kw in ['HOSPITAL', 'MEDICAL', 'PHARMACY']):
        return 'Medical'
    if any(kw in desc for kw in ['UBER', 'OLA', 'RAPIDO', 'CAB']):
        return 'Transport'
    if any(kw in desc for kw in ['PAYMENT RECEIVED', 'PAYMENT', 'IRIS']):
        return 'Payment/Refund'
    if any(kw in desc for kw in ['FEE', 'CHARGE', 'GST', 'SERVICE TAX']):
        return 'Fees & Charges'
    if 'RETAIL OUTLET' in desc:
        return 'Retail'
    if 'SERVICE STATION' in desc:
        return 'Fuel'
    return 'General'
