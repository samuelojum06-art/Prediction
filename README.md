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
P_t = 1 / odds_t

Threshold Condition (Bet Signal)


