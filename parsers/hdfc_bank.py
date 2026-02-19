"""
HDFC Bank Account Statement Parser.
Uses word-position-based extraction (x1 right-edge alignment).
pdfplumber collapses the HDFC table into a mega-row, so we bypass
table extraction and work directly with extracted words.
"""
import pdfplumber
import re

# ── Column positions (right-edge x1) ────────────────────────────────
WITHDRAWAL_X1 = 470
DEPOSIT_X1 = 548
BALANCE_X1 = 627
COL_TOL = 20

# ── Zone boundaries ─────────────────────────────────────────────────
DATE_X0_MAX = 55          # transaction dates at x0 ≈ 33.7
DESC_X0_MIN = 66          # description starts after date
DESC_X0_MAX = 283         # description ends before Chq/Ref (x0 ≈ 285)

Y_TOLERANCE = 3           # group words within this y range
CONTINUATION_MAX_GAP = 50 # max y gap for continuation rows

DATE_PAT = re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4}$')
AMT_PAT = re.compile(r'^-?[\d,]+\.\d{2}$')

SKIP_KEYWORDS = [
    'STATEMENTSUMMARY', 'OPENINGBALANCE', 'CLOSINGBAL',
    'DRCOUNT', 'CRCOUNT', 'DEBITS', 'CREDITS',
]


def parse_hdfc_bank(filepath, password=None):
    """Parse HDFC bank account statement PDF."""
    transactions = []

    with pdfplumber.open(filepath, password=password) as pdf:
        for page in pdf.pages:
            words = page.extract_words(
                keep_blank_chars=True, x_tolerance=2, y_tolerance=2
            )
            if not words:
                continue

            rows = _group_words_by_y(words)
            last_date_y = -999

            for y in sorted(rows.keys()):
                row_words = sorted(rows[y], key=lambda w: w['x0'])

                # ── skip footer / summary rows ──
                row_text = ''.join(
                    w['text'].upper().replace(' ', '') for w in row_words
                )
                if any(kw in row_text for kw in SKIP_KEYWORDS):
                    continue

                # ── check for transaction date ──
                date_word = None
                for w in row_words:
                    if w['x0'] < DATE_X0_MAX and DATE_PAT.match(w['text']):
                        date_word = w
                        break

                if date_word:
                    # ── new transaction ──
                    last_date_y = y
                    desc_parts = []
                    withdrawal = ''
                    deposit = ''
                    balance = ''

                    for w in row_words:
                        text = w['text'].strip()
                        if not text or w is date_word:
                            continue

                        x0, x1 = w['x0'], w['x1']

                        # amount columns (by right-edge x1)
                        if AMT_PAT.match(text.replace(',', '').strip()
                                         if ',' not in text
                                         else text):
                            # re-check with commas removed
                            pass
                        clean = text.replace(',', '')
                        if re.match(r'^-?\d+\.\d{2}$', clean):
                            if abs(x1 - BALANCE_X1) < COL_TOL:
                                balance = float(clean)
                                continue
                            if abs(x1 - DEPOSIT_X1) < COL_TOL:
                                deposit = float(clean)
                                continue
                            if abs(x1 - WITHDRAWAL_X1) < COL_TOL:
                                withdrawal = float(clean)
                                continue

                        # description zone
                        if DESC_X0_MIN <= x0 <= DESC_X0_MAX:
                            desc_parts.append(text)
                        # everything else (chq/ref, value date) → skip

                    description = ' '.join(desc_parts)

                    transactions.append({
                        'date': date_word['text'],
                        'description': description,
                        'debit': withdrawal,
                        'credit': deposit,
                        'balance': balance,
                        'ledger': _determine_ledger(description),
                    })

                else:
                    # ── continuation row → append description ──
                    if (transactions
                            and last_date_y > 0
                            and (y - last_date_y) < CONTINUATION_MAX_GAP):
                        desc_parts = []
                        for w in row_words:
                            x0 = w['x0']
                            if DESC_X0_MIN <= x0 <= DESC_X0_MAX:
                                desc_parts.append(w['text'].strip())
                        if desc_parts:
                            transactions[-1]['description'] += (
                                ' ' + ' '.join(desc_parts)
                            )

    return transactions


# ── helpers ──────────────────────────────────────────────────────────

def _group_words_by_y(words):
    """Group words into rows by y-coordinate (top)."""
    if not words:
        return {}
    sorted_words = sorted(words, key=lambda w: w['top'])
    rows = {}
    for w in sorted_words:
        y = w['top']
        matched = False
        for key in rows:
            if abs(key - y) <= Y_TOLERANCE:
                rows[key].append(w)
                matched = True
                break
        if not matched:
            rows[y] = [w]
    return rows


def _determine_ledger(description):
    desc = description.upper()
    if any(kw in desc for kw in ['UPI', 'IMPS', 'NEFT', 'RTGS']):
        if any(kw in desc for kw in ['ZOMATO', 'SWIGGY']):
            return 'Food & Dining'
        if any(kw in desc for kw in ['ZERODHA', 'GROWW']):
            return 'Investment'
        if any(kw in desc for kw in ['RECHARGE', 'AIRTEL', 'JIO']):
            return 'Utilities'
        return 'Transfer'
    if 'SALARY' in desc:
        return 'Salary'
    if 'INTEREST' in desc:
        return 'Interest'
    if 'ATM' in desc or 'CASH' in desc:
        return 'Cash'
    if 'EMI' in desc:
        return 'EMI/Loan'
    return 'General'
