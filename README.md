# Bethesda Pool Fantasy Football Dashboard

An automated, cloud-hosted dashboard for tracking weekly stats, standings, and awards for the Bethesda Pool Fantasy Football League.

## Overview

This project uses Python to pull weekly matchup data from the Sleeper API, calculate advanced metrics (like Luck % and Total Win %), and generate an interactive HTML dashboard using Plotly. The entire process is automated using GitHub Actions and hosted for free on GitHub Pages.

## Features

* **Automated Weekly Updates:** Runs every Tuesday at 9:00 AM EDT via GitHub Actions.
* **Interactive Charts:** Tracks weekly scores, cumulative wins, and luck percentages.
* **Historical Archives:** Maintains access to previous season dashboards.
* **Discord Integration:** Automatically posts a link to the updated dashboard in the league Discord channel.

## Tech Stack

* **Language:** Python 3.13
* **Libraries:** `pandas`, `plotly`, `sleeper-api-wrapper`
* **Hosting:** GitHub Pages
* **Automation:** GitHub Actions

## Local Setup

If you want to run this project locally, follow these steps:

1. Clone the repository.
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up your local environment variables for Discord integration):
   ```bash
   export DISCORD_WEBHOOK_URL="your_webhook_url_here"
   ```
4. Run the script:
   ```bash
   python generate_report.py
   ```
   
## Project Structure

```text
.
├── .github/workflows/deploy.yml  # Automation configuration
├── archive/                      # Previous season dashboards
├── assets/                       # League logo and images
├── generate_report.py            # Main dashboard generation script
└── requirements.txt              # Python dependencies
```
