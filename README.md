# Bank Statement Parser

A web application that parses Indian bank statement PDFs into structured Excel sheets.

## Supported Banks
- **SBI** Bank & Credit Card
- **HDFC** Bank & Credit Card
- **Yes Bank** & Credit Card
- **IndusInd** Credit Card
- **RBL** Bank & Credit Card
- **Standard Chartered** Bank
- **One Card** Credit Card

## Features
- Upload PDF bank statements (with optional password for protected files)
- Auto-detects bank type using IFSC codes and keywords
- Extracts all transactions with: Serial Number, Date, Description, Debit, Credit, Running Balance, Ledger
- Download parsed data as styled Excel (.xlsx) files
- Smart ledger categorization (Transfer, Food & Dining, Utilities, etc.)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/bank-statement-parser.git
cd bank-statement-parser

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

## How It Works
1. Upload a bank statement PDF
2. The app auto-detects the bank type
3. Transactions are extracted and displayed in a table
4. Click "Download Excel" to get a styled spreadsheet

## Tech Stack
- **Backend:** Python, Flask, pdfplumber
- **Frontend:** HTML/CSS/JavaScript
- **Excel Export:** openpyxl
