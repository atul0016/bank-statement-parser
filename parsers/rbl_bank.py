"""
RBL Bank Account Statement Parser.
Uses word-position-based extraction for reliable column classification.
Columns: Transaction Date | Transaction Details | Cheque ID | Value Date | Withdrawal Amt | Deposit Amt | Balance
"""
import pdfplumber
import re


def parse_rbl_bank(filepath, password=None):
    """Parse RBL Bank account statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            _process_page_words(page, transactions)

    # Clean descriptions
    for txn in transactions:
        desc = re.sub(r'\s+', ' ', txn['description']).strip()
        desc = re.sub(r'\(cid:\d+\)', '', desc).strip()
        txn['description'] = desc
        txn['ledger'] = _determine_ledger(desc)

    return transactions


def _process_page_words(page, transactions):
    """Process RBL Bank page using word positions."""
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    if not words:
        return

    # Fixed column positions (right-edge x1) from PDF analysis
    # Header word detection overrides these incorrectly, so we hardcode them
    withdrawal_x1 = 537
    deposit_x1 = 628
    balance_x1 = 766
    COL_TOL = 25  # slightly larger tolerance for robustness
    header_y = None

    # Find header_y to skip header rows
    for w in words:
        t = w['text'].strip().lower()
        if 'withdrawal' in t or 'transaction date' in t:
            header_y = round(w['top'])
            break

    # Group words by y-position
    rows = {}
    for w in words:
        y = round(w['top'])
        rows.setdefault(y, []).append(w)

    # Skip lines with summary keywords
    skip_re = re.compile(
        r'accountholder|customer address|home branch|phone|email|nomination|'
        r'cif id|a/c currency|a/c type|a/c status|statement of transaction|'
        r'period:|transaction date|transaction details|cheque id|value date|'
        r'statement summary|opening balance|closing balance|eff avail|'
        r'date and time|page \d|disclaimer|lien|sanction|drawing power|'
        r'branch timings|call center|branch phone|total',
        re.I,
    )
    date_re = re.compile(r'^\d{1,2}/\d{1,2}/\d{4}$')
    amount_re = re.compile(r'^[\d,]+\.\d{2}$')

    for y in sorted(rows.keys()):
        if header_y is not None and y <= header_y:
            continue

        rw = sorted(rows[y], key=lambda w: w['x0'])
        line_text = ' '.join(w['text'] for w in rw)

        if skip_re.search(line_text):
            continue

        # Classify amounts by x1 position
        amounts = {}
        non_amount_words = []
        for w in rw:
            txt = w['text'].strip()
            if amount_re.match(txt):
                diffs = [
                    ('debit', abs(w['x1'] - withdrawal_x1)),
                    ('credit', abs(w['x1'] - deposit_x1)),
                    ('balance', abs(w['x1'] - balance_x1)),
                ]
                best = min(diffs, key=lambda d: d[1])
                if best[1] <= COL_TOL:
                    amounts[best[0]] = txt
                else:
                    non_amount_words.append(w)
            else:
                non_amount_words.append(w)

        if not amounts:
            # Description-only line
            if transactions:
                desc_words = [w['text'] for w in non_amount_words
                              if w['x0'] > 15 and w['x1'] < 400]
                if desc_words:
                    transactions[-1]['description'] += ' ' + ' '.join(desc_words)
            continue

        # Transaction row - extract date
        date_str = ''
        for w in non_amount_words:
            if date_re.match(w['text'].strip()) and w['x0'] < 100:
                date_str = w['text'].strip()
                break

        if not date_str and transactions:
            date_str = transactions[-1]['date']

        # Description: words in middle area
        desc_parts = []
        for w in non_amount_words:
            txt = w['text'].strip()
            if date_re.match(txt):
                continue
            if w['x0'] >= 70 and w['x1'] < 380:
                desc_parts.append(txt)
        description = ' '.join(desc_parts)

        transactions.append({
            'date': date_str,
            'description': description,
            'debit': amounts.get('debit', ''),
            'credit': amounts.get('credit', ''),
            'balance': amounts.get('balance', ''),
            'ledger': '',
        })


def _determine_ledger(description):
    desc = description.upper()
    if any(kw in desc for kw in ['UPI', 'IMPS', 'NEFT', 'RTGS']):
        if any(kw in desc for kw in ['SWIGGY', 'ZOMATO']):
            return 'Food & Dining'
        if any(kw in desc for kw in ['NETFLIX', 'SPOTIFY', 'APPLE']):
            return 'Entertainment'
        return 'Transfer'
    if 'INT.PD' in desc or 'INTEREST' in desc:
        return 'Interest'
    if 'GST' in desc:
        return 'Fees & Charges'
    if 'SMS' in desc or 'ALERT' in desc:
        return 'Fees & Charges'
    if 'IMPS CHARGE' in desc:
        return 'Fees & Charges'
    return 'General'
