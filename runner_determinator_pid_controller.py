#!/usr/bin/env python3
# /// script
# dependencies = [
#   "simple_pid",
# ]
# ///
"""
AWS Credit Optimization using PID Controller
Automatically adjusts the percentage of CI jobs sent to the LF AWS account
to maximize credit usage without exceeding the budget.
"""

import argparse
from datetime import datetime, timedelta
import json
import logging
import os
from logging.handlers import RotatingFileHandler
import re
import yaml
import requests
from simple_pid.PID import PID




# Set up logging
log_formatter = logging.Formatter(
    '%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# File handler with rotation
file_handler = RotatingFileHandler(
    'controller.log',
    maxBytes=5*1024*1024,
    backupCount=3
)
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

class GitHubExperimentParser:
    """Parses rollout percentage from a GitHub issue comment."""
    def __init__(self, comment_url, repo="pytorch/test-infra", token=None):
        self.comment_url = comment_url
        self.repo = repo
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.issue_number, self.comment_id = self.extract_comment_info(
            comment_url
        )

    @staticmethod
    def extract_comment_info(url):
        """Extract the issue number and comment ID from a GitHub comment URL."""
        match = re.search(r'/issues/(\d+)#issuecomment-(\d+)', url)
        if not match:
            raise ValueError("Invalid GitHub comment URL")
        issue_number, comment_id = match.groups()
        return issue_number, comment_id

    def fetch_comment_body(self):
        """Fetch the body of a GitHub issue comment using the API."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        api_url = (
            f"https://api.github.com/repos/{self.repo}/"
            f"issues/comments/{self.comment_id}"
        )
        resp = requests.get(api_url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()["body"]

    @staticmethod
    def parse_rollout_perc(comment_body):
        """Parse the rollout_perc value for 'lf' from the YAML block in the comment body."""
        yaml_match = re.search(r'(?s)(experiments:.*?)(?:\n\s*\n|$)', comment_body)
        if not yaml_match:
            raise ValueError("No YAML experiments block found in comment")
        yaml_block = yaml_match.group(1)
        # Remove markdown code fences
        yaml_block = yaml_block.replace('```', '').strip()
        docs = list(yaml.safe_load_all(yaml_block))
        data = docs[0]
        return data["experiments"]["lf"]["rollout_perc"]

    def get_lf_rollout_perc(self):
        """Get the current LF rollout percentage from the GitHub comment."""
        comment_body = self.fetch_comment_body()
        return self.parse_rollout_perc(comment_body)

class AWSCreditOptimizer:
    """PID controller for optimizing AWS credit usage and job distribution."""
    def __init__(self,
                 total_credits=500000,  # $500k in free credits
                 safety_margin=0.02,    # 2% safety margin
                 update_interval=3600,  # Update every hour
                 rollout_perc=35):      # Default rollout percentage
        self.total_credits = total_credits
        # Target 98% usage
        self.target_credits = total_credits * (1 - safety_margin)
        self.update_interval = update_interval
        self.rollout_perc = rollout_perc

        # PID parameters (these will need tuning based on your system)
        # These values are tuned to track the spending trajectory closely
        # Proportional gain - responds to current error
        Kp = 2.0    # pylint: disable=invalid-name
        # Integral gain - corrects accumulated error
        Ki = 0.15   # pylint: disable=invalid-name
        # Derivative gain - dampens oscillations
        Kd = 0.5    # pylint: disable=invalid-name

        # Initialize PID controller
        # Output will be the adjustment to the base percentage
        self.pid = PID(Kp, Ki, Kd, setpoint=0)
        # Allow adjustments in both directions
        self.pid.output_limits = (-40, 40)

        # Track last update time for proper integral calculation
        self.last_update_time = None
        self.current_spend = 0

    def get_target_spend_rate(self, current_spend, days_elapsed, days_in_month):
        """Calculate the ideal spend rate to hit target by month end"""
        days_remaining = days_in_month - days_elapsed

        if days_remaining <= 0:
            return 0, 0  # Month is over

        # Linear trajectory: where we should be now
        ideal_spend = (days_elapsed / days_in_month) * self.target_credits

        # How much we need to spend per day to reach target
        remaining_budget = self.target_credits - current_spend
        target_daily_spend = remaining_budget / days_remaining

        return ideal_spend, target_daily_spend

    def _calculate_date_info(self, current_date=None):
        """Calculate date-related information for the current month."""
        now = current_date or datetime.now()
        # Calculate days in current month
        days_in_month = (
            datetime(now.year, now.month + 1, 1) - timedelta(days=1)
        ).day
        days_elapsed = now.day
        return now, days_in_month, days_elapsed

    def _calculate_trajectory_metrics(self, current_spend, days_elapsed, days_in_month):
        """Calculate trajectory-related metrics."""
        ideal_spend, target_daily_spend = self.get_target_spend_rate(
            current_spend, days_elapsed, days_in_month
        )
        trajectory_error = ideal_spend - current_spend
        error_percentage = (trajectory_error / self.target_credits) * 100
        return (
            ideal_spend,
            target_daily_spend,
            trajectory_error,
            error_percentage
        )

    def _calculate_base_percentage(self, daily_spend_rate, target_daily_spend, rollout_perc):
        """Calculate the base percentage for job routing."""
        if daily_spend_rate > 0 and target_daily_spend > 0:
            current_percentage_estimate = rollout_perc
            return min(100, max(0, current_percentage_estimate))
        return 50.0

    def _log_calculation_details(self, calculation_data):
        """Log detailed calculation information for debugging.

        Args:
            calculation_data: Dictionary containing all calculation metrics
        """
        logger.info(
            "Day %d/%d",
            calculation_data['days_elapsed'],
            calculation_data['days_in_month']
        )
        logger.info(
            "Current spend: $%.2f, Ideal: $%.2f",
            calculation_data['current_spend'],
            calculation_data['ideal_spend']
        )
        logger.info(
            "Target daily spend: $%.2f",
            calculation_data['target_daily_spend']
        )
        logger.info(
            "Daily spend rate: $%.2f",
            calculation_data['daily_spend_rate']
        )
        logger.info(
            "Trajectory error: $%.2f (%.1f%%)",
            calculation_data['trajectory_error'],
            calculation_data['error_percentage']
        )
        logger.info(
            "Base: %.1f%%, PID adj: %.1f%%, Final: %.1f%%",
            calculation_data['base_percentage'],
            calculation_data['pid_adjustment'],
            calculation_data['adjustment'],
        )
        logger.info(
            "P=%.2f, I=%.2f, D=%.2f",
            self.pid.components[0],
            self.pid.components[1],
            self.pid.components[2],
        )

    def calculate_percentage_split(
        self, current_spend, daily_spend_rate, rollout_perc, current_date=None
    ):
        """
        Calculate the percentage of jobs to send to the LF AWS account

        Args:
            current_spend: Current month's spend on LF AWS account
            daily_spend_rate: Average daily spend rate (last 24h or similar)
            current_date: Optional date for simulation purposes

        Returns:
            percentage: 0-100 representing % of jobs for LF AWS account
        """
        # Safety check: if we're at or over budget, stop using credits
        if current_spend >= self.target_credits:
            logger.warning(
                "At or over target spend: $%.2f >= $%.2f",
                current_spend,
                self.target_credits,
            )
            return 0

        # Get date information
        _, days_in_month, days_elapsed = self._calculate_date_info(current_date)

        # Calculate trajectory metrics
        ideal_spend, target_daily_spend, trajectory_error, error_percentage = (
            self._calculate_trajectory_metrics(
                current_spend, days_elapsed, days_in_month
            )
        )

        # Calculate base percentage
        base_percentage = self._calculate_base_percentage(
            daily_spend_rate, target_daily_spend, rollout_perc
        )

        # Calculate PID adjustment and final percentage
        pid_adjustment = self.pid(-error_percentage)
        if pid_adjustment is None:
            pid_adjustment = 0
        adjustment = max(0, min(100, base_percentage + pid_adjustment))

        # Prepare calculation data for logging
        calculation_data = {
            'days_elapsed': days_elapsed,
            'days_in_month': days_in_month,
            'current_spend': current_spend,
            'ideal_spend': ideal_spend,
            'target_daily_spend': target_daily_spend,
            'daily_spend_rate': daily_spend_rate,
            'trajectory_error': trajectory_error,
            'error_percentage': error_percentage,
            'base_percentage': base_percentage,
            'pid_adjustment': pid_adjustment,
            'adjustment': adjustment,
        }

        # Log calculation details
        self._log_calculation_details(calculation_data)

        return adjustment

    def update_pid_tuning(self, Kp=None, Ki=None, Kd=None): # pylint: disable=invalid-name
        """Adjust PID parameters if needed"""
        if Kp is not None:
            self.pid.Kp = Kp  # type: ignore
        if Ki is not None:
            self.pid.Ki = Ki  # type: ignore
        if Kd is not None:
            self.pid.Kd = Kd  # type: ignore
        logger.info(
            "Updated PID tuning: Kp=%.2f, Ki=%.2f, Kd=%.2f",
            self.pid.Kp,  # type: ignore
            self.pid.Ki,  # type: ignore
            self.pid.Kd,  # type: ignore
        )




# Production implementation
class AWSCreditController:
    """Production-ready controller with persistence, AWS integration, and job routing logic."""

    def __init__(self, config_file='pid_state.json', rollout_perc=35, days=1):
        self.config_file = config_file
        self.optimizer = AWSCreditOptimizer(rollout_perc=rollout_perc)
        self.days = days
        self.load_state()
        self.tenant_id = 'cc951ada-105f-40b1-8305-c65861490a90'
        self.api_base_url = (
            f"https://api.ternary.app/analytics/query/load?"
            f"tenant_id={self.tenant_id}"
        )

    def _get_api_key(self):
        """Get the Ternary API key from environment variables"""
        ternary_api_key = os.getenv('TERNARY_API_KEY')
        if not ternary_api_key:
            raise ValueError(
                "TERNARY_API_KEY environment variable is not set. "
                "Please create a .env file with your API key."
            )
        return ternary_api_key

    def _query_ternary_api(self, start_date, end_date, project_id):
        """
        Helper method to query the Ternary API for spend data.

        Args:
            start_date (str): ISO format start date
            end_date (str): ISO format end date
            project_id (str): The project ID to get spend for

        Returns:
            float: The spend amount in credits (positive number)

        Raises:
            requests.exceptions.RequestException: For any API request errors
            ValueError: For invalid response format
        """
        headers = {
            'Authorization': self._get_api_key(),
            'accept': 'application/json',
            'content-type': 'application/json'
        }

        payload = {
            "end_time": end_date,
            "start_time": start_date,
            "data_source": "Billing",
            "dimensions": [
                "projectId",
                "projectName"
            ],
            "measures": [
                "credits"
            ],
            "pre_agg_filters": [
                {
                    "operator": "equals",
                    "schema_field_name": "projectId",
                    "values": [project_id]
                }
            ]
        }

        try:
            response = requests.post(
                self.api_base_url,
                headers=headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()

            response_json = response.json()

            if ("response" in response_json and
                isinstance(response_json["response"], list)):
                if response_json["response"]:
                    first_item = response_json["response"][0]
                    if "credits" in first_item:
                        return abs(first_item["credits"])
                    raise ValueError("Response does not contain credits data")
                return 0.0  # No spend data found
            raise ValueError("Invalid response format from API")

        except requests.exceptions.HTTPError as http_err:
            logger.error("HTTP error occurred: %s", http_err)
            logger.error("Response content: %s", response.text)
            raise
        except requests.exceptions.ConnectionError as conn_err:
            logger.error("Connection error occurred: %s", conn_err)
            raise
        except requests.exceptions.Timeout as timeout_err:
            logger.error("Timeout error occurred: %s", timeout_err)
            raise
        except requests.exceptions.RequestException as req_err:
            logger.error("An unexpected error occurred: %s", req_err)
            raise

    def get_current_spend(self, project_id="391835788720"):
        """
        Get the current spend for a specific project from the Ternary API.

        Args:
            project_id (str): The project ID to get spend for.
                             Defaults to the main project ID.

        Returns:
            float: The current spend in credits (positive number)
        """
        # Get current local time
        now_local = datetime.now()
        end_date = now_local.strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'

        # Get start of current month
        start_of_month = datetime(now_local.year, now_local.month, 1)
        start_date = start_of_month.strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'

        return self._query_ternary_api(start_date, end_date, project_id)

    def get_recent_spend_rate(self, project_id="391835788720", days=1):
        """
        Calculate recent spend rate for the specified number of days (local time).
        Args:
            project_id (str): The project ID to get spend for.
                             Defaults to the main project ID.
            days (int): Number of days to look back for spend rate calculation.
                       Defaults to 1 day.
        Returns:
            float: The spend rate in credits per day for the specified period (positive number)
        """
        # Calculate the start date based on the specified number of days
        start_date_calc = datetime.now() - timedelta(days=days)
        start_date = (
            start_date_calc.replace(hour=0, minute=0, second=0, microsecond=0)
            .strftime('%Y-%m-%dT%H:%M:%S')
            + '.000Z'
        )
        end_date = (
            start_date_calc.replace(hour=23, minute=59, second=59, microsecond=0)
            .strftime('%Y-%m-%dT%H:%M:%S')
            + '.000Z'
        )

        # Debug prints (optional, can be removed)
        print(f"Start date: {start_date}")
        print(f"End date: {end_date}")

        # Get spend for the specified period and calculate daily rate
        credits_period = self._query_ternary_api(
            start_date, end_date, project_id
        )
        daily_rate = credits_period / days
        print(f"Credits for {days} day(s): {credits_period}, Daily rate: {daily_rate}")
        return daily_rate

    def load_state(self):
        """Load PID state from file to maintain continuity"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                # Restore PID integral term for smooth continuation
                if 'integral' in state:
                    self.optimizer.pid._integral = state['integral']  # type: ignore # pylint: disable=protected-access
                logger.info("Loaded previous PID state")
        except FileNotFoundError:
            logger.info("No previous state found, starting fresh")

    def save_state(self):
        """Save PID state for next run"""
        state = {
            'integral': self.optimizer.pid._integral,  # type: ignore # pylint: disable=protected-access
            'last_update': datetime.now().isoformat(),
            'components': self.optimizer.pid.components
        }
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(state, f)

    def update_job_routing(self, percentage):
        """Update the CI/CD system with new routing percentage"""
        # In production, this would update your job routing configuration
        # Could be updating an environment variable, API call, or config file
        logger.info(
            "Updating job routing to %.1f%% on LF AWS account",
            percentage
        )


    def run_update_cycle(self):
        """Main update cycle - run this as a cron job"""
        try:
            # Get current metrics
            current_spend = self.get_current_spend()
            spend_rate = self.get_recent_spend_rate(days=self.days)

            # Calculate new percentage
            percentage = self.optimizer.calculate_percentage_split(
                current_spend, spend_rate, self.optimizer.rollout_perc
            )

            # Update routing
            self.update_job_routing(percentage)

            # Save state for next run
            self.save_state()

            # Log summary
            logger.info(
                "Update complete: %.1f%% -> LF Rollout Percentage",
                percentage
            )

        except (requests.RequestException, ValueError, OSError) as e:
            logger.error("Error in update cycle: %s", e)
            # In production, send alert to ops team

def run_production_controller(days=1):
    """Run the production controller"""
    github_comment_url = (
        "https://github.com/pytorch/test-infra/issues/5132"
        "#issuecomment-2076772891"
    )
    parser = GitHubExperimentParser(github_comment_url)
    rollout_perc = parser.get_lf_rollout_perc()
    controller = AWSCreditController(rollout_perc=rollout_perc, days=days)
    controller.run_update_cycle()


if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="AWS Credit Optimization using PID Controller"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days to look back for spend rate calculation (default: 1)"
    )
    args = parser.parse_args()

    # Run the production controller with the specified days
    run_production_controller(days=args.days)

    # Example of production usage:
    # controller = AWSCreditController()
    # controller.run_update_cycle()
