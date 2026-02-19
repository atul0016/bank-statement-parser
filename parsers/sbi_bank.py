"""
SBI Bank Account Statement Parser.
Handles State Bank of India savings/current account statements.
Uses word-position-based extraction with right-edge (x1) alignment.
"""
import pdfplumber
import re

# Column x1 defaults (right-edge alignment) – overridden per page if header found
_DEFAULT_DEBIT_X1 = 414.4
_DEFAULT_CREDIT_X1 = 477.8
_DEFAULT_BALANCE_X1 = 557.0
_COL_TOLERANCE = 15  # pixels


def parse_sbi_bank(filepath, password=None):
    """Parse SBI bank account statement PDF."""
    transactions = []
    col_x1 = None  # will be set from first header encountered
    state = {'last_date': '', 'last_year': ''}  # persist across pages

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            col_x1 = _process_page(page, transactions, col_x1, state)

    # Post-process: clean descriptions and recalculate ledger
    # (continuation lines are added after initial transaction creation)
    footer_re = re.compile(
        r'\b(bank never asks|do not share|computer generated|page \d|'
        r'disclaimer|helpline|customer care|toll free|Ref No\./Cheque|'
        r'Date No\.)\b.*$',
        re.I,
    )
    for txn in transactions:
        desc = txn['description']
        desc = re.sub(r'\s+', ' ', desc).strip()
        desc = footer_re.sub('', desc).strip()
        desc = re.sub(r'\(cid:\d+\)', '', desc).strip()
        txn['description'] = desc
        txn['ledger'] = _determine_ledger(desc)

    return transactions


def _process_page(page, transactions, col_x1, state):
    """Process one page and return the column x1 tuple for reuse."""
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    if not words:
        return col_x1

    # --- Detect column positions from header ---
    debit_x1, credit_x1, balance_x1 = (
        col_x1 if col_x1 else (_DEFAULT_DEBIT_X1, _DEFAULT_CREDIT_X1, _DEFAULT_BALANCE_X1)
    )
    header_y = None
    for w in words:
        t = w['text'].strip().lower()
        if t == 'debit' and w['x0'] > 350:
            debit_x1 = w['x1']
            header_y = round(w['top'])
        elif t == 'credit' and w['x0'] > 400:
            credit_x1 = w['x1']
        elif t == 'balance' and w['x0'] > 480:
            balance_x1 = w['x1']
    col_x1 = (debit_x1, credit_x1, balance_x1)

    # --- Group words by y-position ---
    rows = {}
    for w in words:
        y = round(w['top'])
        rows.setdefault(y, []).append(w)

    # --- Identify transaction rows (ones with amounts) ---
    date_re = re.compile(r'^\d{1,2}$')
    month_names = {'jan', 'feb', 'mar', 'apr', 'may', 'jun',
                   'jul', 'aug', 'sep', 'oct', 'nov', 'dec'}
    skip_re = re.compile(
        r'txn date|value date|account name|account number|account description|'
        r'branch|drawing power|interest rate|mod balance|cif no|ckycr|'
        r'ifs code|micr|nomination|balance as on|account statement|'
        r'please do not|computer generated|indian financial|magnetic ink|'
        r'page no|address|opening balance|closing balance|lien amount',
        re.I,
    )
    last_date = state.get('last_date', '')
    last_year = state.get('last_year', '')  # track year across pages

    for y in sorted(rows.keys()):
        if header_y is not None and y <= header_y:
            continue  # skip everything at or above the header

        rw = sorted(rows[y], key=lambda w: w['x0'])
        line_text = ' '.join(w['text'] for w in rw)

        if skip_re.search(line_text):
            continue

        # Classify amounts by right-edge alignment
        amounts = {}  # 'debit'|'credit'|'balance' → text
        non_amount_words = []
        for w in rw:
            txt = w['text'].strip()
            if _is_amount(txt):
                col = _classify_col(w['x1'], debit_x1, credit_x1, balance_x1)
                if col:
                    amounts[col] = txt
                else:
                    non_amount_words.append(w)
            else:
                non_amount_words.append(w)

        if not amounts:
            # Continuation / description-only line → append to previous txn
            if transactions:
                extra_parts = []
                for w in non_amount_words:
                    if w['x0'] > 90 and w['x1'] < 400:
                        txt = w['text'].strip()
                        # Skip year that leaked from value date
                        if re.match(r'^\d{4}$', txt) and w['x0'] < 200:
                            state['last_year'] = txt
                            continue
                        extra_parts.append(txt)
                extra = ' '.join(extra_parts)
                if extra.strip():
                    transactions[-1]['description'] += ' ' + extra.strip()
            continue

        # --- Build transaction ---
        # Extract date from left-side words (x0 < 100)
        date_str = ''
        date_parts = []
        consumed_positions = set()  # track word indices used for date
        for idx, w in enumerate(non_amount_words):
            if w['x0'] < 100:
                t = w['text'].strip()
                if date_re.match(t) and not date_parts:
                    date_parts.append(t)
                    consumed_positions.add(idx)
                elif date_parts and t.lower()[:3] in month_names:
                    date_parts.append(t)
                    consumed_positions.add(idx)
                elif date_parts and re.match(r'^\d{4}$', t):
                    date_parts.append(t)
                    last_year = t
                    consumed_positions.add(idx)
                    break
        if date_parts:
            # If year is missing, append the last known year
            if len(date_parts) == 2 and last_year:
                date_parts.append(last_year)
            date_str = ' '.join(date_parts)
            last_date = date_str
        else:
            date_str = last_date

        # Description: words between date area and amount columns
        # Skip date words and value-date words (second date at x0 > 90)
        # Also skip noise words: TO, BY, TRANSFER, TRANSFER-, FROM
        noise_words = {'TO', 'BY', 'TRANSFER-', 'TRANSFER', 'FROM'}
        desc_parts = []
        for idx, w in enumerate(non_amount_words):
            x0 = w['x0']
            txt = w['text'].strip()
            # Skip words consumed by date extraction
            if idx in consumed_positions:
                continue
            # Skip value date (second date between x0=90-145)
            if x0 >= 90 and x0 < 145:
                if date_re.match(txt) or txt.lower()[:3] in month_names or re.match(r'^\d{4}$', txt):
                    if re.match(r'^\d{4}$', txt):
                        last_year = txt
                    continue
            # Skip year "2025" that leaked into description area
            if re.match(r'^\d{4}$', txt) and x0 < 200:
                last_year = txt
                continue
            # Include words in description area (x0 >= 130 and x1 < 370)
            if x0 >= 130 and w['x1'] < 370:
                if txt not in noise_words:
                    desc_parts.append(txt)
        description = ' '.join(desc_parts)
        # Clean up description
        description = re.sub(r'\s+', ' ', description).strip()
        description = re.sub(r'\(cid:\d+\)', '', description).strip()

        transactions.append({
            'date': date_str,
            'description': description,
            'debit': amounts.get('debit', ''),
            'credit': amounts.get('credit', ''),
            'balance': amounts.get('balance', ''),
            'ledger': _determine_ledger(description),
        })

    state['last_date'] = last_date
    state['last_year'] = last_year
    return col_x1


def _classify_col(x1, debit_x1, credit_x1, balance_x1):
    """Classify an amount into debit/credit/balance by its right-edge x1."""
    diffs = [
        ('debit', abs(x1 - debit_x1)),
        ('credit', abs(x1 - credit_x1)),
        ('balance', abs(x1 - balance_x1)),
    ]
    best = min(diffs, key=lambda d: d[1])
    if best[1] <= _COL_TOLERANCE:
        return best[0]
    return None


def _is_amount(text):
    """Check if text looks like an amount (number with optional commas and decimal)."""
    cleaned = text.replace(',', '').strip()
    return bool(re.match(r'^\d+\.\d{2}$', cleaned))


def _determine_ledger(description):
    """Determine ledger category from transaction description."""
    desc = description.upper()
    if any(kw in desc for kw in ['UPI', 'IMPS', 'NEFT', 'RTGS']):
        if any(kw in desc for kw in ['ZOMATO', 'SWIGGY', 'FOOD']):
            return 'Food & Dining'
        if any(kw in desc for kw in ['NETFLIX', 'SPOTIFY', 'AMAZON PRIME', 'HOTSTAR']):
            return 'Entertainment'
        if any(kw in desc for kw in ['ZERODHA', 'GROWW', 'ANGEL', 'BROKER']):
            return 'Investment'
        if any(kw in desc for kw in ['ELECTRICITY', 'WATER', 'GAS', 'BROADBAND', 'AIRTEL', 'JIO', 'RECHARGE']):
            return 'Utilities'
        if any(kw in desc for kw in ['INSURANCE', 'LIC', 'POLICY']):
            return 'Insurance'
        if any(kw in desc for kw in ['RENT']):
            return 'Rent'
        if any(kw in desc for kw in ['SBI CARD', 'CREDIT CARD', 'CC PAYMENT', 'SBICARDSAN']):
            return 'Credit Card Payment'
        return 'Transfer'
    if 'SALARY' in desc or 'SAL' in desc:
        return 'Salary'
    if 'INTEREST' in desc or 'INT.COLL' in desc:
        return 'Interest'
    if 'ATM' in desc or 'CASH' in desc:
        return 'Cash'
    if 'EMI' in desc:
        return 'EMI/Loan'
    if 'TAX' in desc or 'GST' in desc or 'TDS' in desc:
        return 'Tax'
    return 'General'
