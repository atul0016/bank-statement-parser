"""
HDFC Credit Card Statement Parser.
Handles HDFC Bank credit card statements (Tata Neu, etc.).
Format: DATE & TIME | TRANSACTION DESCRIPTION | Base NeuCoins | AMOUNT | PI
"""
import pdfplumber
import re


def parse_hdfc_credit(filepath, password=None):
    """Parse HDFC Credit Card statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            _process_hdfc_credit_text(text, transactions)

    return transactions


def _process_hdfc_credit_text(text, transactions):
    """Process HDFC credit card statement from text."""
    lines = text.split('\n')

    # HDFC credit card: date pattern DD/MM/YYYY| HH:MM
    date_pattern = re.compile(r'^(\d{1,2}/\d{1,2}/\d{4})\s*\|?\s*(\d{1,2}:\d{2})?')
    amount_pattern = re.compile(r'[₹C]?\s*([\d,]+\.\d{2})')

    in_transactions = False
    current_txn = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()

        # Detect transaction section
        if 'domestic transaction' in lower or 'international transaction' in lower:
            in_transactions = True
            continue

        if any(kw in lower for kw in ['important information', 'useful links', 'note:', 'benefits on your card',
                                       'offers on your card', 'how to read gst']):
            in_transactions = False
            continue

        if 'date & time' in lower or 'transaction description' in lower:
            continue

        if not in_transactions:
            continue

        date_match = date_pattern.match(line)
        if date_match:
            if current_txn:
                _finalize_hdfc_credit_txn(current_txn, transactions)

            date_str = date_match.group(1)
            rest = line[date_match.end():].strip()

            # Remove leading pipe
            rest = rest.lstrip('|').strip()

            # Find amounts: look for C or ₹ followed by amount, or just amount at end
            amounts = []
            # HDFC uses format like "C 3,541.30" or "+ C 35.06"
            amt_matches = list(re.finditer(r'[+\-]?\s*[₹C]\s*([\d,]+\.\d{2})', rest))
            
            if amt_matches:
                last_amt = amt_matches[-1]
                amount_str = last_amt.group(1).replace(',', '')
                # Check if it's a credit (+ sign or contains credit indicators)
                prefix = rest[:last_amt.start()].strip()
                is_credit = '+' in rest[max(0, last_amt.start()-5):last_amt.start()]
                
                desc = rest[:amt_matches[0].start()].strip()
                # Remove NeuCoins notation
                desc = re.sub(r'[+\-]?\s*\d+\s*$', '', desc).strip()

                current_txn = {
                    'date': date_str,
                    'description': desc,
                    'amount': float(amount_str),
                    'is_credit': is_credit
                }
            else:
                # Try plain amount
                plain_amounts = amount_pattern.findall(rest)
                desc = rest
                for a in plain_amounts:
                    desc = desc.replace(a, '').strip()
                desc = re.sub(r'[₹C+\-l]\s*$', '', desc).strip()
                desc = re.sub(r'\s+', ' ', desc).strip()

                amount = float(plain_amounts[-1].replace(',', '')) if plain_amounts else 0

                current_txn = {
                    'date': date_str,
                    'description': desc,
                    'amount': amount,
                    'is_credit': '+' in line[:20] if plain_amounts else False
                }
        elif current_txn and line:
            # Continuation line - could be part of description
            if not any(kw in line.lower() for kw in ['page ', 'note:', 'neucoins']):
                # Check if it has amount
                amt_matches = list(re.finditer(r'[+\-]?\s*[₹C]\s*([\d,]+\.\d{2})', line))
                if amt_matches and not current_txn.get('amount'):
                    current_txn['amount'] = float(amt_matches[-1].group(1).replace(',', ''))
                    current_txn['is_credit'] = '+' in line[:10]
                    desc_part = line[:amt_matches[0].start()].strip()
                    if desc_part:
                        current_txn['description'] += ' ' + desc_part
                elif not re.match(r'^[+\-]?\s*\d+\s*$', line):  # Skip NeuCoins-only lines
                    current_txn['description'] += ' ' + line

    if current_txn:
        _finalize_hdfc_credit_txn(current_txn, transactions)


def _finalize_hdfc_credit_txn(txn, transactions):
    """Finalize HDFC credit card transaction."""
    amount = txn.get('amount', 0)
    if amount == 0:
        return

    desc = re.sub(r'\s+', ' ', txn['description']).strip()
    # Clean up common artifacts
    desc = re.sub(r'\s*l\s*$', '', desc)
    desc = re.sub(r'^\+\s*', '', desc)
    
    if not desc:
        return

    # PETRO SURCHARGE WAIVER is a credit
    is_credit = txn.get('is_credit', False)
    if 'SURCHARGE WAIVER' in desc.upper() or 'REVERSAL' in desc.upper() or 'REFUND' in desc.upper():
        is_credit = True
    if 'PAYMENT' in desc.upper() and 'RECEIVED' in desc.upper():
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
    if any(kw in desc for kw in ['ZOMATO', 'SWIGGY', 'FOOD', 'RESTAURANT', 'STARBUCKS', 'TACO',
                                  'BARBEQUE', 'MCDONALDS', 'KFC', 'CAFE', 'DOMINOS', 'PIZZA']):
        return 'Food & Dining'
    if any(kw in desc for kw in ['PETROL', 'DIESEL', 'FUEL', 'AUTO FILLS', 'HP ', 'BPCL']):
        return 'Fuel'
    if any(kw in desc for kw in ['AMAZON', 'FLIPKART', 'MYNTRA', 'AJIO']):
        return 'Shopping Online'
    if any(kw in desc for kw in ['NETFLIX', 'SPOTIFY', 'HOTSTAR']):
        return 'Entertainment'
    if any(kw in desc for kw in ['BLINKIT', 'ZEPTO', 'BIGBASKET', 'GROCERY', 'DMART']):
        return 'Groceries'
    if any(kw in desc for kw in ['H AND M', 'ZARA', 'BATA', 'JOCKEY', 'MARKS AND SPENCER',
                                  'CLOTHING', 'APPAREL', 'INDIVINITY', 'BANGLES']):
        return 'Clothing & Accessories'
    if any(kw in desc for kw in ['FITNESS', 'GYM']):
        return 'Health & Fitness'
    if any(kw in desc for kw in ['SURCHARGE WAIVER', 'REVERSAL', 'REFUND']):
        return 'Adjustment'
    return 'General'
