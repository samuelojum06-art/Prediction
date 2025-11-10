# Prediction

# Overview

This project explores behavioral inefficiencies in live sports betting markets — analyzing how odds fluctuate during a match as if they were financial time-series data.
By treating betting markets like financial markets, the model attempts to identify market overreactions when a team’s probability of winning drops too sharply after an event (e.g., conceding a goal).
The project simulates, tests, and visualizes the profitability of a logic-based backtesting strategy using data science and quantitative methods — without requiring machine learning.

# Goal
To determine whether sports markets misprice odds in the short term due to behavioral bias — and if those inefficiencies can be exploited through a rule-based betting strategy.

# Logic

The strategy works as follows:

1. Collect or simulate minute-by-minute odds for two teams over a 90-minute match.

2. Convert those odds into implied probabilities.

3. Track when a team’s probability drops by a certain percentage (threshold).

4. When the drop exceeds a chosen threshold (e.g., −10%), simulate a “buy” signal (a bet).

5. Repeat across multiple matches and compare results against benchmarks:

   Always betting on favorites

   Always betting on underdogs

   Random betting

   Behavioral-threshold strategy

6. Visualize performance and evaluate metrics like total profit, win rate, and average return per bet.

# Formula's Used

Implied Probability
$P_t = \dfrac{1}{\text{odds}_t}$

Threshold Condition (Bet Signal)
$B_t = 1$ if $\dfrac{P_t - P_0}{P_0} \le \theta$, otherwise $B_t = 0$

Return per Bet
$R_t = \text{odds}_t - 1$ if the team wins, and $R_t = -1$ if the team loses

Portfolio Cumulative P & L
$\text{P&L} = \sum_{i=1}^{N} B_i \cdot R_i$

Behavioral Edge (Advanced Extension)

$E_t = P_{t}^{\text{real}} - P_{t}^{\text{market}}$
If $E_t > 0$, the market underestimates the team’s chance — a potential buy opportunity.

# Future Plans

The upcoming version will feature:

Adjustable thresholds (−5 %, −10 %, −20 %)

Real-time backtest visualization

Comparison vs. random and baseline models

# Next Steps

 Multi-threshold backtesting

 Kelly criterion bet sizing

 Historical probability datasets for behavioral edge

 Integration with real odds APIs (OddsAPI, Betfair)

 Interactive Streamlit dashboard

# Author
Samuel Ojum
University of Arizona — Eller College of Management
Quantitative Finance • Data Science • Behavioral Market Research
