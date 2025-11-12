## Live Betting ... Behaviorally Mispriced or Probably Right? ##
### [Ryder Rhoads](mailto:ryder.rhoads@rady.ucsd.edu) 
University of California, San Diego · Rady School of Management  
### [Samuel Ojum](mailto:samuelojum@arizona.edu)
University of Arizona · Eller College of Management  


## Overview
This project explores **behavioral inefficiencies in live sports betting markets**, using Polymarket data as a proxy for real-time crowd sentiment. The goal is to test whether live odds **overreact to short-term events** (like a goal or penalty) and whether a quantitative, logic-based strategy can identify profitable corrections.


## Research Objective
- Identify short-term overreactions in implied probabilities.  
- Measure reversion behavior within live odds using **minute-by-minute price history**.  
- Evaluate profitability of rule-based “buy-the-dip” strategies.

## Data & Tools
This repository now includes:
- **Polymarket API Clients** (Gamma + CLOB) — for fetching market and price history data  
- **Rate Limit Management** — automatic throttling and backoff (`ratelimit.py`)  
- **MongoDB Integration** — local database for storing market snapshots  
- **Documentation & Setup Guides**
  - `setup.md` – quickstart environment setup  
  - `mongodb_setup.md` – local database configuration  
  - `API_RATE_LIMITS.md` – official endpoint constraints
