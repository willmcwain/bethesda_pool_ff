#!/usr/bin/env python
# coding: utf-8

# In[9]:


import requests
import os
import re
import shutil
import subprocess
import pandas as pd
import seaborn as sns
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio
import numpy as np
import matplotlib.pyplot as plt

REPORT_FILE = "league_dashboard.html"
DEPLOY_DIR = "deploy"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

pd.set_option('display.max_colwidth', None)


# In[10]:


from sleeper.api import league, player

# League ID
#league_id = "1257253128554688512" #=== 2025 season league ID ===
league_id = "1389362279690010624"
my_league = league.get_league(league_id=league_id)

matchup_json = league.get_matchups_for_week(league_id=league_id, week=1)
#display(JSON(matchup_json))

# Get users and rosters
users = league.get_users_in_league(league_id=league_id)
rosters = league.get_rosters(league_id=league_id)

team_names = {}

for user in users:
    username = user["display_name"]
    team_name = user["metadata"]["team_name"]
    team_names[username] = team_name

# Convert to DataFrames
df_users = pd.DataFrame(users)   # columns: user_id, display_name
df_rosters = pd.DataFrame(rosters)  # columns: roster_id, owner_id

# Merge to map roster_id -> manager name
df_rosters_users = df_rosters.merge(
    df_users,
    left_on='owner_id',
    right_on='user_id',
    how='left'
)

# Keep only the columns you need
df_rosters_users = df_rosters_users[['roster_id', 'display_name']]
df_rosters_users = df_rosters_users.rename(columns={'display_name':'Manager'})

# Get player dictionary
all_players = player.get_all_players(sport="nfl")


# In[11]:


# Define fantasy position order
position_order = {'QB': 0, 'RB': 1, 'WR': 2, 'TE': 3, 'K': 4, 'DST': 5}

data_long = []

for roster in rosters:
    # Find manager name
    manager = next(
        (u['display_name'] for u in users if u['user_id'] == roster['owner_id']),
        'Unknown Manager'
    )

    # Loop over players in roster
    for pid in roster.get('players', []):
        player_info = all_players.get(pid)

        if player_info:
            # Regular player
            name = player_info.get('full_name') or f"{player_info.get('first_name', '')}{player_info.get('last_name', '')}".strip()
            position = player_info.get('position', '')
        else:
            # Team defenses
            name = pid
            position = 'DST'

        data_long.append({
            'Manager': manager,
            'Player': name,
            'Position': position,
            'PositionOrder': position_order.get(position, 99)   # Number for sorting
        })

# Create DataFrame
df_roster_long = pd.DataFrame(data_long)

# Sort by Manager, PositionOrder, then Player
df_roster_long.sort_values(by=['Manager', 'PositionOrder', 'Player'], inplace=True)

# Drop helper column
df_roster_long = df_roster_long.drop(columns='PositionOrder')

# Display table
#display(HTML(df_roster_long.to_html(index=False)))


# In[13]:


weekly_data = []
week = 1

while True:
    # Get the team-centric matchup data for the week
    matchup_entries = league.get_matchups_for_week(league_id=league_id, week=week)
    if not matchup_entries:
        break  # no more weeks

    df_week = pd.DataFrame(matchup_entries)
    df_week['Points'] = [entry['points'] for entry in matchup_entries]

    df_week['Week'] = week

    # Map roster_id → Manager using your df_rosters_users
    df_week = df_week.merge(
        df_rosters_users[['roster_id', 'Manager']], 
        on='roster_id', 
        how='left'
    )

    if df_week['Points'].max() == 0:
        break # no games completed yet

    # Determine weekly winners by comparing points within each matchup_id
    df_week['Win'] = False  # initialize
    for mid, group in df_week.groupby('matchup_id'):
        if len(group) == 2:
            if group.iloc[0]['points'] > group.iloc[1]['points']:
                df_week.loc[group.index[0], 'Win'] = True
                df_week.loc[group.index[1], 'Win'] = False
            else:
                df_week.loc[group.index[0], 'Win'] = False
                df_week.loc[group.index[1], 'Win'] = True
        else:
            # Handle bye weeks or odd numbers
            df_week.loc[group.index, 'Win'] = False

    weekly_data.append(df_week)
    week += 1

# Concatenate all weeks into one DataFrame
df_weekly = pd.concat(weekly_data, ignore_index=True)

# --- Compute Metrics ---

# Team Win %
df_weekly['TeamWinPct'] = df_weekly['Win'].apply(lambda x: 100 if x else 0)

# Total Win % (percent of other teams beaten that week)
def total_win_pct(row, df):
    week_data = df[df['Week'] == row['Week']]
    total_opponents = len(week_data) - 1
    if total_opponents == 0:
        return np.nan
    wins_if_played_all = sum(row['points'] > week_data['points'])
    return (wins_if_played_all / total_opponents) * 100

df_weekly['TotalWinPct'] = df_weekly.apply(lambda row: total_win_pct(row, df_weekly), axis=1)

# Luck %
df_weekly['LuckPct'] = df_weekly['TeamWinPct'] - df_weekly['TotalWinPct']

# Cumulative wins
df_weekly['CumulativeWins'] = df_weekly.groupby('Manager')['Win'].cumsum()

# Cumulative average points
df_weekly['CumulativeAvgPoints'] = df_weekly.groupby('Manager')['points'].cumsum() / df_weekly.groupby('Manager').cumcount().add(1)


# Weekly award calculations
weekly_awards_extended = []

for week in df_weekly['Week'].unique():
    week_data = df_weekly[df_weekly['Week'] == week].copy()

    # Existing awards
    high = week_data.loc[week_data['points'].idxmax()]
    low = week_data.loc[week_data['points'].idxmin()]

    # New awards
    luckiest = week_data.loc[week_data['LuckPct'].idxmax()]
    unluckiest = week_data.loc[week_data['LuckPct'].idxmin()]

    # Over/Under performer compared to cumulative average (up to previous week)
    if week == 1:
        overperformer = high
        underperformer = low
        delta_over = overperformer['points']
        delta_under = underperformer['points']
    else:
        week_data['DeltaVsAvg'] = week_data['points'] - week_data['CumulativeAvgPoints']
        overperformer = week_data.loc[week_data['DeltaVsAvg'].idxmax()]
        underperformer = week_data.loc[week_data['DeltaVsAvg'].idxmin()]
        delta_over = overperformer['DeltaVsAvg']
        delta_under = underperformer['DeltaVsAvg']

    weekly_awards_extended.append({
        'Week': week,
        'HighestScore': f"{team_names[high['Manager']]} ({high['points']})",
        'LowestScore': f"{team_names[low['Manager']]} ({low['points']})",
        'LuckiestManager': f"{team_names[luckiest['Manager']]} ({luckiest['LuckPct']:.1f}%)",
        'UnluckiestManager': f"{team_names[unluckiest['Manager']]} ({unluckiest['LuckPct']:.1f}%)",
        'Overperformer': f"{team_names[overperformer['Manager']]} ({delta_over:.1f})",
        'Underperformer': f"{team_names[underperformer['Manager']]} ({delta_under:.1f})"
    })

df_weekly_awards_extended = pd.DataFrame(weekly_awards_extended)

# Column ordering
category_order = [
    'HighestScore',
    'LowestScore',
    'LuckiestManager',
    'UnluckiestManager',
    'Overperformer',
    'Underperformer'
]

# Columns as weeks
df_awards_wide_ext = df_weekly_awards_extended.melt(
    id_vars='Week',
    value_vars=category_order,
    var_name='Category',
    value_name='Value'
)

df_awards_wide_ext['Category'] = pd.Categorical(
    df_awards_wide_ext['Category'],
    categories=category_order,
    ordered=True
)

df_awards_wide_ext = df_awards_wide_ext.pivot(
    index='Category',
    columns='Week',
    values='Value'
)

#display(df_awards_wide_ext)


# In[14]:


# Set general style
sns.set(style="whitegrid")
plt.rcParams["figure.figsize"] = (12,6)

df_weekly["display_name"] = df_weekly["Manager"].map(team_names).fillna(df_weekly["Manager"])

# --- 1. Weekly Scores per Manager ---
fig1 = px.line(
    df_weekly,
    x='Week',
    y='Points',
    color='display_name',
    markers=True,                 # show the points
    hover_data={'Points': ':.1f'} # show value on hover
)
fig1.update_layout(
    title="Weekly Scores per Manager",
    xaxis_title="Week",
    yaxis_title="Points",
    xaxis=dict(tickmode='linear')
)
fig1.show()

# --- 2. Cumulative Average Points ---
fig2 = px.line(
    df_weekly,
    x='Week',
    y='CumulativeAvgPoints',
    color='display_name',
    markers=True,
    hover_data={'CumulativeAvgPoints': ':.2f'}
)
fig2.update_layout(
    title="Cumulative Average Points per Manager",
    xaxis_title="Week",
    yaxis_title="Average Points",
    xaxis=dict(tickmode='linear')
)
fig2.show()

# --- 3. Cumulative Wins ---
fig3 = px.line(
    df_weekly,
    x='Week',
    y='CumulativeWins',
    color='display_name',
    markers=True,
    hover_data={'CumulativeWins': ':.1f'}
)
fig3.update_layout(
    title="Cumulative Wins per Manager",
    xaxis_title="Week",
    yaxis_title="Wins",
    xaxis=dict(tickmode='linear')
)
fig3.show()

# --- 4. Weekly Luck Percentage ---
fig4 = px.line(
    df_weekly,
    x='Week',
    y='LuckPct',
    color='display_name',
    markers=True,
    hover_data={'LuckPct': ':.1f'}
)
fig4.add_hline(y=0, line_dash="dash", line_color="gray")  # reference line
fig4.update_layout(
    title="Weekly Luck % per Manager",
    xaxis_title="Week",
    yaxis_title="Luck % (-100 to 100%)",
    xaxis=dict(tickmode='linear')
)
fig4.show()


# In[15]:


category_map = {
    "HighestScore": "Highest Score",
    "LowestScore": "Lowest Score",
    "LuckiestManager": "Luckiest Manager",
    "UnluckiestManager": "Unluckiest Manager",
    "Overperformer": "Overperformer",
    "Underperformer": "Underperformer"
}

# Transpose the table so Weeks are rows instead of columns
df_table_transposed = df_awards_wide_ext.T.reset_index()
df_table_transposed.columns = ['Week'] + list(df_awards_wide_ext.index.map(category_map))

# Format the Week column to look nicer (e.g., "Week 1" instead of just "1")
df_table_transposed['Week'] = 'Week ' + df_table_transposed['Week'].astype(str)

table_values = [df_table_transposed[col].astype(str).tolist() for col in df_table_transposed.columns]

fig = make_subplots(
    rows=2, cols=2,
    subplot_titles=("Weekly Scores", "Cumulative Avg Points",
                    "Weekly Luck %", "Cumulative Wins"),
    vertical_spacing=0.1
)

managers = df_weekly['display_name'].unique()
df_weekly['Week_Shifted'] = df_weekly['Week'] - 1

manager_colors = {
    manager: px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)]
    for i, manager in enumerate(managers)
}

for manager in managers:
    manager_data = df_weekly[df_weekly['display_name'] == manager]
    # Weekly Scores
    fig.add_trace(
        go.Scatter(
            x=manager_data['Week_Shifted'],
            y=manager_data['Points'],
            mode='lines+markers',
            name=manager,
            marker=dict(color=manager_colors[manager]),
            showlegend=True,
            legendgroup=manager,
            hovertemplate='%{y:.2f} points' 
        ),
        row=1, col=1
    )

    # Cumulative Avg Points
    fig.add_trace(
        go.Scatter(
            x=manager_data['Week_Shifted'],
            y=manager_data['CumulativeAvgPoints'],
            mode='lines+markers',
            name=manager,
            marker=dict(color=manager_colors[manager]),
            showlegend=False,
            legendgroup=manager,
            hovertemplate='%{y:.2f} points' 
        ),
        row=1, col=2
    )
    # Cumulative Wins
    fig.add_trace(
        go.Scatter(
            x=manager_data['Week_Shifted'],
            y=manager_data['CumulativeWins'],
            mode='lines+markers',
            name=manager,
            marker=dict(color=manager_colors[manager]),
            showlegend=False,
            legendgroup=manager,
            hovertemplate='%{y:.0f} wins' 
        ),
        row=2, col=2
    )
    # Weekly Luck %
    fig.add_trace(
        go.Scatter(
            x=manager_data['Week_Shifted'],
            y=manager_data['LuckPct'],
            mode='lines+markers',
            name=manager,
            marker=dict(color=manager_colors[manager]),
            showlegend=False,
            legendgroup=manager,
            hovertemplate='%{y:.2f}%' 
        ),
        row=2, col=1
    )

fig.update_layout(
    autosize=True,
    showlegend=True,
    title_text="Bethesda Pool Weekly Stats Dashboard",
    height=800
)

fig.update_yaxes(dtick=1, row=2, col=2)

fig.update_yaxes(
    tickvals=list(range(-100, 101, 50)),  # ticks at -100, -80, ..., 100
    ticktext=[f"{v}%" for v in range(-100, 101, 50)],
    row=2, col=1
)

max_week = df_weekly['Week'].max()

fig.update_xaxes(
    tickvals=list(range(max_week + 1)),  # only show ticks 1, 2, 3, ...
    ticktext=['Week 1'] + [str(i+1) for i in range(1, max_week)] + [''], # labels for each tick
    range=[-0.05 * max_week, max_week]  # optional: limits axis to your data
)

# Define your navigation bar HTML
nav_bar_html = """
<div style="background-color: #2D3139; overflow: hidden; padding: 10px; font-family: sans-serif; display: flex; align-items: center;">
  <img src="assets/league_logo.jpeg" alt="League Logo" style="height: 50px; margin-right: 15px; margin-left: 10px;">
  <a style="color: #f2f2f2; text-align: center; padding: 14px 16px; text-decoration: none; font-size: 17px;" href="index.html">Current Season</a>
  <a style="color: #f2f2f2; text-align: center; padding: 14px 16px; text-decoration: none; font-size: 17px;" href="archive/2025_season.html">2025 Season</a>
</div>
"""

# 1. Write the charts to the file
fig.write_html(
    REPORT_FILE,
    include_plotlyjs='cdn',
    full_html=True,
    config={'responsive': True}
)

# 2. Convert your DataFrame to a clean HTML Table
table_html = df_table_transposed.to_html(index=False, classes='awards-table', border=0)

# 3. Define your custom CSS and Nav Bar
custom_html = f"""
{nav_bar_html}
<style>
  body {{
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  
  .awards-table {{ width: 95%; border-collapse: collapse; margin: 30px auto 50px auto; font-family: sans-serif; }}
  .awards-table th {{ background-color: lightgrey; padding: 10px; text-align: left; }}
  .awards-table td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
</style>
"""

# 4. Inject everything into the final file
with open(REPORT_FILE, 'r', encoding='utf-8') as f:
    html_content = f.read()

footer_html = """
<div style="text-align: center; padding: 20px; color: #666; font-family: sans-serif; font-size: 12px; margin-top: auto; border-top: 1px solid #ddd;">
  &copy; 2026 Will McWain. Made for Bethesda Pool Fantasy Football League. All rights reserved.
</div>
"""

if '<body>' in html_content:
    html_content = html_content.replace('<body>', f'<body>\n{custom_html}')
    html_content = html_content.replace('</body>', f'{table_html}\n{footer_html}\n</body>')

with open(REPORT_FILE, 'w', encoding='utf-8') as f:
    f.write(html_content)

# In[16]:

# === Prep deploy folder ===
if os.path.exists(DEPLOY_DIR):
    shutil.rmtree(DEPLOY_DIR)
os.makedirs(DEPLOY_DIR, exist_ok=True)

if os.path.exists("assets"):
    shutil.copytree("assets", os.path.join(DEPLOY_DIR, "assets"))

# Copy the new dashboard
shutil.copyfile(REPORT_FILE, os.path.join(DEPLOY_DIR, "index.html"))

# Copy the archive folder (if it exists)
if os.path.exists("archive"):
    shutil.copytree("archive", os.path.join(DEPLOY_DIR, "archive"))

print("Local build complete. Ready for GitHub Pages deployment.")

# === Send link to Discord ===
# Define your permanent GitHub Pages URL here
GITHUB_PAGES_URL = "https://willmcwain.github.io/bethesda_pool_ff/"

data = {"content": f"Here’s this week’s report: {GITHUB_PAGES_URL}"}

try:
    response = requests.post(WEBHOOK_URL, json=data)
    if response.status_code == 204:
        print("Report link sent to Discord!")
    else:
        print(f"Failed to send to Discord: {response.status_code}, {response.text}")
except Exception as e:
    print(f"Error sending to Discord: {e}")
