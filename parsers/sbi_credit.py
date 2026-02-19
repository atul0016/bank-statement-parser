"""
SBI Credit Card Statement Parser.
Handles SBI Card credit card statements.
Format: Date | Transaction Description | Amount (Dr/Cr)
"""
import pdfplumber
import re


def parse_sbi_credit(filepath, password=None):
    """Parse SBI Credit Card statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            _process_sbi_credit_text(text, transactions)

    return transactions


def _process_sbi_credit_text(text, transactions):
    """Process SBI credit card statement from text."""
    lines = text.split('\n')
    
    # SBI credit card format:
    # Date  Description  Amount (Dr/Cr)
    # Date pattern: DD/MM/YYYY or DD Mon YYYY
    date_pattern = re.compile(
        r'^(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+\w{3}\s+\d{4}|\d{1,2}\s\w{3}\s\d{2})'
    )
    amount_pattern = re.compile(r'([\d,]+\.\d{2})\s*(Dr|Cr|DR|CR|D|C)?\.?\s*$')

    in_transaction_section = False
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()

        # Detect transaction section
        if 'transaction details' in lower or 'domestic transaction' in lower or 'international transaction' in lower:
            in_transaction_section = True
            continue

        # Skip non-transaction sections
        if any(kw in lower for kw in ['account summary', 'statement summary', 'payment due',
                                       'credit limit', 'available credit', 'shop & smile',
                                       'reward', 'points expiry', 'gstin', 'hsn code',
                                       'important information', 'useful links', 'page ']):
            # If we have context, might be ending transaction section
            if 'page ' in lower and current_txn:
                continue  # page breaks
            # Don't set in_transaction_section to False for page breaks
            if 'page ' not in lower:
                in_transaction_section = False
            continue

        if not in_transaction_section:
            # Also try to find transactions outside explicit section headers
            date_match = date_pattern.match(line)
            if date_match:
                amt_match = amount_pattern.search(line)
                if amt_match:
                    in_transaction_section = True

        if not in_transaction_section:
            continue

        date_match = date_pattern.match(line)
        if date_match:
            # Save previous
            if current_txn:
                _finalize_sbi_credit_txn(current_txn, transactions)

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
            # Continuation line
            amt_match = amount_pattern.search(line)
            if amt_match:
                if not current_txn['amount']:
                    current_txn['amount'] = amt_match.group(1)
                    current_txn['dr_cr'] = (amt_match.group(2) or '').upper()
                    desc_part = line[:amt_match.start()].strip()
                    if desc_part:
                        current_txn['description'] += ' ' + desc_part
            else:
                # Check if it's just numbers or irrelevant
                if not line.replace(' ', '').replace('-', '').isdigit() and \
                   not line.lower().startswith('ref no'):
                    current_txn['description'] += ' ' + line

    if current_txn:
        _finalize_sbi_credit_txn(current_txn, transactions)


def _finalize_sbi_credit_txn(txn, transactions):
    """Finalize and add an SBI credit card transaction."""
    if not txn.get('amount') or not txn.get('date'):
        return

    amount = txn['amount'].replace(',', '')
    try:
        amount_float = float(amount)
    except ValueError:
        return

    desc = re.sub(r'\s+', ' ', txn['description']).strip()
    # Remove ref numbers from description
    desc = re.sub(r'\s*-\s*Ref\s*No\s*:\s*\S+', '', desc, flags=re.IGNORECASE)

    dr = txn['dr_cr']
    if dr in ('CR', 'C') or 'PAYMENT RECEIVED' in desc.upper() or 'REVERSAL' in desc.upper() or 'REFUND' in desc.upper():
        debit = ''
        credit = amount_float
    else:
        debit = amount_float
        credit = ''

    # Skip zero amounts
    if amount_float == 0:
        return

    transactions.append({
        'date': txn['date'],
        'description': desc,
        'debit': debit,
        'credit': credit,
        'balance': '',
        'ledger': _determine_ledger(desc)
    })


def _determine_ledger(description):
    """Determine ledger category for credit card transactions."""
    desc = description.upper()
    if any(kw in desc for kw in ['ZOMATO', 'SWIGGY', 'FOOD', 'RESTAURANT', 'CAFE', 'PIZZA',
                                  'BURGER', 'DOMINOS', 'STARBUCKS', 'TACO', 'BARBEQUE']):
        return 'Food & Dining'
    if any(kw in desc for kw in ['AMAZON', 'FLIPKART', 'MYNTRA', 'AJIO', 'MEESHO']):
        return 'Shopping Online'
    if any(kw in desc for kw in ['NETFLIX', 'SPOTIFY', 'HOTSTAR', 'PRIME VIDEO', 'YOUTUBE']):
        return 'Entertainment'
    if any(kw in desc for kw in ['PETROL', 'DIESEL', 'FUEL', 'PETROLEUM', 'HP ', 'BPCL', 'IOCL',
                                  'AUTO FILLS', 'OIL', 'BHARAT PETRO']):
        return 'Fuel'
    if any(kw in desc for kw in ['AIRTEL', 'JIO', 'VODAFONE', 'RECHARGE', 'ELECTRICITY', 'WATER',
                                  'GAS', 'BROADBAND', 'BILL PAY']):
        return 'Utilities'
    if any(kw in desc for kw in ['HOSPITAL', 'MEDICAL', 'PHARMACY', 'CHEMIST', 'DOCTOR',
                                  'HEALTH', 'APOLLO', 'FORTIS', 'MEDIC']):
        return 'Medical'
    if any(kw in desc for kw in ['UBER', 'OLA', 'RAPIDO', 'IRCTC', 'MAKEMYTRIP', 'YATRA',
                                  'AIRLINES', 'FLIGHT', 'TRAIN', 'CAB', 'TRAVEL']):
        return 'Travel'
    if any(kw in desc for kw in ['GROCERY', 'BIGBASKET', 'BLINKIT', 'ZEPTO', 'DMART',
                                  'SUPERMARKET', 'GROFERS', 'NATURE', 'BASKET']):
        return 'Groceries'
    if any(kw in desc for kw in ['EMI', 'LOAN']):
        return 'EMI/Loan'
    if any(kw in desc for kw in ['INSURANCE', 'LIC', 'POLICY']):
        return 'Insurance'
    if any(kw in desc for kw in ['PAYMENT RECEIVED', 'PAYMENT', 'REVERSAL', 'REFUND']):
        return 'Payment/Refund'
    if any(kw in desc for kw in ['FEE', 'CHARGE', 'ANNUAL', 'SURCHARGE', 'GST', 'TAX', 'SERVICE TAX']):
        return 'Fees & Charges'
    if any(kw in desc for kw in ['APPAREL', 'CLOTHING', 'FASHION', 'MARKS AND SPENCER', 'H AND M',
                                  'ZARA', 'BATA', 'JOCKEY', 'LEVI']):
        return 'Clothing'
    return 'General'
