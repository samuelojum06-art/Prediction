# Setup Guide

Hi Sam,

I’ve added Polymarket API clients to your project so you can:
- Fetch markets from Polymarket and store them in your database.
- Filter markets that include a `gameStartTime` or `gameId`.
- Convert the `gameStartTime` (ISO format) into an epoch timestamp.
- Use the **Clob Client** to fetch the market’s price history at `t₀` (start time).
- Pull price history with a fidelity of 1 minute (`fidelity=1`) to get minute-by-minute prices.

---

## Environment Setup

1. **Create a virtual environment**
   ```bash
   python -m venv .venv
   # or if that doesn't work
   python3 -m venv .venv
2. **Activate a virtual environment**
   ```bash
   # for Mac / Linux
   source .venv/bin/activate
   # or on Windows
   .venv\Scripts\Activate.ps1
3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   pip install -e .
3. **Import / Use Clients**
   ```python
   from clients.gamma_client import PolymarketGammaClient 
   from clients.clob_client import PolymarketCLOB

