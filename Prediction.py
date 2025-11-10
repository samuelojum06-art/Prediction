import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

np.random.seed(42)

def simulate_match(match_id, minutes=90):
    """Generate fake minute-by-minute odds for two teams"""
    odds_A = np.linspace(1.5, 3.0, minutes) + np.random.normal(0, 0.05, minutes)
    odds_B = np.linspace(3.0, 1.8, minutes) + np.random.normal(0, 0.05, minutes)

    df = pd.DataFrame({
        'match_id': match_id,
        'minute': np.arange(1, minutes + 1),
        'odds_A': np.clip(odds_A, 1.01, None),
        'odds_B': np.clip(odds_B, 1.01, None)
    })

    # This is the Implied probabilities ----
    df['prob_A'] = 1 / df['odds_A']
    df['prob_B'] = 1 / df['odds_B']

    # Here we woould randomly assign winner
    winner = np.random.choice(['A', 'B'], p=[0.5, 0.5])
    df['winner'] = winner
    return df

# thsi makes a simulation of 10 matches
matches = [simulate_match(i) for i in range(10)]
df_all = pd.concat(matches, ignore_index=True)


threshold = -0.10  # 10% drop in implied probability
initial_probs = df_all.groupby('match_id')[['prob_A', 'prob_B']].first().rename(columns={'prob_A':'P0_A','prob_B':'P0_B'})

df_all = df_all.merge(initial_probs, on='match_id')

# percent change in probabilities
df_all['pct_change_A'] = (df_all['prob_A'] - df_all['P0_A']) / df_all['P0_A']
df_all['pct_change_B'] = (df_all['prob_B'] - df_all['P0_B']) / df_all['P0_B']

# buy signals
df_all['signal_A'] = np.where(df_all['pct_change_A'] <= threshold, 1, 0)
df_all['signal_B'] = np.where(df_all['pct_change_B'] <= threshold, 1, 0)

def bet_return(row, team):
    """Return profit/loss for a single signal"""
    signal = row[f'signal_{team}']
    odds = row[f'odds_{team}']
    winner = row['winner']
    if signal == 1:
        if winner == team:
            return odds - 1  
        else:
            return -1        
    else:
        return 0             

df_all['return_A'] = df_all.apply(lambda x: bet_return(x, 'A'), axis=1)
df_all['return_B'] = df_all.apply(lambda x: bet_return(x, 'B'), axis=1)


summary = df_all.groupby('match_id').agg({
    'signal_A':'sum',
    'signal_B':'sum',
    'return_A':'sum',
    'return_B':'sum'
}).reset_index()

summary['total_return'] = summary['return_A'] + summary['return_B']
summary['bets_made'] = summary['signal_A'] + summary['signal_B']


total_bets = summary['bets_made'].sum()
total_pnl = summary['total_return'].sum()
avg_return = total_pnl / total_bets if total_bets > 0 else 0


df_all['portfolio_return'] = df_all['return_A'] + df_all['return_B']
df_all['cumulative_PnL'] = df_all.groupby('match_id')['portfolio_return'].cumsum()


plt.figure(figsize=(10, 5))
for mid, group in df_all.groupby('match_id'):
    plt.plot(group['minute'], group['cumulative_PnL'], label=f'Match {mid}', alpha=0.6)
plt.axhline(0, color='gray', linestyle='--')
plt.title('Cumulative P&L per Match (Behavioral Odds Strategy)')
plt.xlabel('Minute')
plt.ylabel('Cumulative P&L')
plt.legend()
plt.show()

# summary
print("========== BACKTEST SUMMARY ==========")
print(f"Total Matches Simulated: {summary.shape[0]}")
print(f"Total Bets Made: {total_bets}")
print(f"Total P&L: {total_pnl:.2f}")
print(f"Average Return per Bet: {avg_return:.3f}")
print("======================================")
print(summary[['match_id', 'bets_made', 'total_return']])

