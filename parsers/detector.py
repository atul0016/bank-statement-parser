"""
Bank type detector and main parsing dispatcher.
Reads the PDF text and detects which bank the statement belongs to,
then dispatches to the appropriate parser.
"""
import pdfplumber
import re
from parsers.sbi_bank import parse_sbi_bank
from parsers.sbi_credit import parse_sbi_credit
from parsers.hdfc_bank import parse_hdfc_bank
from parsers.hdfc_credit import parse_hdfc_credit
from parsers.yes_bank import parse_yes_bank
from parsers.yes_credit import parse_yes_credit
from parsers.rbl_bank import parse_rbl_bank
from parsers.rbl_credit import parse_rbl_credit
from parsers.indusind_credit import parse_indusind_credit
from parsers.one_credit import parse_one_credit
from parsers.standard_bank import parse_standard_bank


def detect_bank_type(text, first_page_text=''):
    """Detect bank type from PDF text content.
    
    Uses a two-tier approach:
    1. IFSC code from first page (most reliable)
    2. Credit card / bank-specific keyword patterns
    
    Args:
        text: Full text from first 3 pages of PDF
        first_page_text: Text from first page only (for IFSC-based detection)
    """
    text_lower = text.lower()
    fp_lower = (first_page_text or text).lower()  # first page for primary detection

    # ── TIER 1: Credit Card Statements (no IFSC codes) ──
    # Check these first as they have very specific markers

    # One Credit Card – very distinctive format
    if 'one credit card' in text_lower:
        return 'one_credit'

    # IndusInd Credit Card
    if 'indusind' in fp_lower and ('credit card' in fp_lower or 'indusind bank' in fp_lower) and \
       ('previous balance' in fp_lower or 'card statement' in fp_lower or 'purchases' in fp_lower):
        return 'indusind_credit'

    # Yes Credit Card
    if 'credit card statement' in fp_lower and 'yes bank' in fp_lower:
        return 'yes_credit'
    if 'yes bank' in fp_lower and 'card number' in fp_lower and 'credit limit' in fp_lower:
        return 'yes_credit'

    # SBI Credit Card
    if 'sbi card' in fp_lower and ('credit limit' in fp_lower or 'stmt no' in fp_lower):
        return 'sbi_credit'
    if ('xxxx xxxx xxxx' in fp_lower or 'stmt no' in fp_lower) and \
       'sbi' in fp_lower and 'credit limit' in fp_lower:
        return 'sbi_credit'

    # HDFC Credit Card (Tata Neu / standard format)
    if ('neucoins' in fp_lower or 'tata neu' in fp_lower):
        return 'hdfc_credit'
    if 'hdfc bank credit card' in fp_lower or \
       ('hdfc' in fp_lower and 'credit card' in fp_lower and ('card no' in fp_lower or 'statement date' in fp_lower)):
        return 'hdfc_credit'

    # RBL Credit Card
    if 'rbl bank' in fp_lower and ('credit limit' in fp_lower or 'min. amt' in fp_lower or \
       'the month gone by' in fp_lower or 'account summary' in fp_lower):
        return 'rbl_credit'

    # ── TIER 2: Bank Statements – use IFSC code from first page ──
    # Extract IFSC codes from first page only
    ifsc_matches = re.findall(r'\b([A-Z]{4}0[A-Z0-9]{6})\b', first_page_text or text)
    ifsc_prefix = ''
    if ifsc_matches:
        ifsc_prefix = ifsc_matches[0][:4].upper()

    # Map IFSC prefix to bank type
    ifsc_bank_map = {
        'SBIN': 'sbi_bank',
        'YESB': 'yes_bank',
        'SCBL': 'standard_bank',
        'HDFC': 'hdfc_bank',
        'RATN': 'rbl_bank',
        'INDB': 'indusind_credit',  # IndusInd bank
    }
    if ifsc_prefix in ifsc_bank_map:
        bank = ifsc_bank_map[ifsc_prefix]
        # Double-check: if detected as bank but text suggests credit card
        if bank == 'hdfc_bank' and 'credit card' in fp_lower and 'credit limit' in fp_lower:
            return 'hdfc_credit'
        return bank

    # ── TIER 3: Keyword fallback (no IFSC found) ──
    # SBI Bank
    if ('state bank' in fp_lower or 'sbin' in fp_lower) and \
       ('account statement' in fp_lower or 'txn date' in fp_lower or 'regular sb' in fp_lower):
        return 'sbi_bank'

    # HDFC Bank
    if 'hdfc' in fp_lower and ('account statement' in fp_lower or 'savings' in fp_lower or 'current account' in fp_lower):
        return 'hdfc_bank'

    # Yes Bank
    if ('yes bank' in fp_lower or 'yesb' in fp_lower) and \
       ('saving' in fp_lower or 'transaction details for your account' in fp_lower or 'statement of account' in fp_lower):
        return 'yes_bank'

    # RBL Bank
    if 'rbl bank' in fp_lower and ('account' in fp_lower):
        return 'rbl_bank'

    # Standard Chartered Bank
    if 'standard chartered' in fp_lower:
        return 'standard_bank'

    # Generic fallbacks
    if 'sbi' in fp_lower and 'credit limit' in fp_lower:
        return 'sbi_credit'
    if 'hdfc' in fp_lower:
        return 'hdfc_bank'
    if 'yes bank' in fp_lower:
        return 'yes_bank'

    return 'unknown'


def detect_and_parse(filepath, password=None):
    """Main entry point: detect bank type and parse accordingly."""
    # Extract text to detect bank type
    full_text = ''
    first_page_text = ''
    try:
        with pdfplumber.open(filepath, password=password) as pdf:
            for i, page in enumerate(pdf.pages[:3]):
                page_text = page.extract_text() or ''
                if i == 0:
                    first_page_text = page_text
                full_text += page_text + '\n'
    except Exception as e:
        if 'password' in str(e).lower() or 'encrypted' in str(e).lower():
            raise Exception('This PDF is password-protected. Please provide the password.')
        raise

    if not full_text.strip():
        return None

    bank_type = detect_bank_type(full_text, first_page_text)
    
    print(f"Detected bank type: {bank_type}")

    parser_map = {
        'sbi_bank': ('SBI Bank', parse_sbi_bank),
        'sbi_credit': ('SBI Credit Card', parse_sbi_credit),
        'hdfc_bank': ('HDFC Bank', parse_hdfc_bank),
        'hdfc_credit': ('HDFC Credit Card', parse_hdfc_credit),
        'yes_bank': ('Yes Bank', parse_yes_bank),
        'yes_credit': ('Yes Credit Card', parse_yes_credit),
        'rbl_bank': ('RBL Bank', parse_rbl_bank),
        'rbl_credit': ('RBL Credit Card', parse_rbl_credit),
        'indusind_credit': ('IndusInd Credit Card', parse_indusind_credit),
        'one_credit': ('One Credit Card', parse_one_credit),
        'standard_bank': ('Standard Chartered Bank', parse_standard_bank),
    }

    if bank_type not in parser_map:
        return None

    bank_label, parser_func = parser_map[bank_type]
    transactions = parser_func(filepath, password=password)

    if not transactions:
        return None

    # Assign serial numbers
    for i, txn in enumerate(transactions):
        txn['serial'] = i + 1

    # Calculate running balance if missing
    _fill_running_balance(transactions)

    return {
        'bank_type': bank_label,
        'transactions': transactions,
        'account_info': ''
    }


def _fill_running_balance(transactions):
    """Fill in running balance if not present, by accumulating debit/credit."""
    has_balance = any(
        txn.get('balance') not in (None, '', '0', 0)
        for txn in transactions
    )
    if has_balance:
        return

    # Try to calculate from first known balance
    running = 0.0
    for txn in transactions:
        debit = _to_float(txn.get('debit', 0))
        credit = _to_float(txn.get('credit', 0))
        running = running - debit + credit
        txn['balance'] = round(running, 2)


def _to_float(val):
    """Convert value to float, handling commas and empty strings."""
    if val in (None, '', 0):
        return 0.0
    try:
        return float(str(val).replace(',', '').replace('₹', '').replace('Rs.', '').strip())
    except (ValueError, TypeError):
        return 0.0
