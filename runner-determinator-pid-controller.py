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

from simple_pid import PID
from datetime import datetime, timedelta
import time
import json
import logging
import requests
import os
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler



# Set up logging
log_formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)

# File handler with rotation
file_handler = RotatingFileHandler('controller.log', maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(log_formatter)
logger.addHandler(file_handler)

class AWSCreditOptimizer:
    def __init__(self,
                 total_credits=500000,  # $500k in free credits
                 safety_margin=0.02,    # 2% safety margin
                 update_interval=3600): # Update every hour

        self.total_credits = total_credits
        self.target_credits = total_credits * (1 - safety_margin)  # Target 98% usage
        self.update_interval = update_interval

        # PID parameters (these will need tuning based on your system)
        # These values are tuned to track the spending trajectory closely
        Kp = 2.0    # Proportional gain - responds to current error
        Ki = 0.15   # Integral gain - corrects accumulated error  
        Kd = 0.5    # Derivative gain - dampens oscillations

        # Initialize PID controller
        # Output will be the adjustment to the base percentage
        self.pid = PID(Kp, Ki, Kd, setpoint=0)
        self.pid.output_limits = (-40, 40)  # Allow adjustments in both directions
        
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

    def calculate_percentage_split(self, current_spend, daily_spend_rate, current_date=None):
        """
        Calculate the percentage of jobs to send to the LF AWS account

        Args:
            current_spend: Current month's spend on LF AWS account
            daily_spend_rate: Average daily spend rate (last 24h or similar)
            current_date: Optional date for simulation purposes

        Returns:
            percentage: 0-100 representing % of jobs for LF AWS account
        """
        # Get current date info
        now = current_date or datetime.now()
        days_in_month = (datetime(now.year, now.month + 1, 1) - timedelta(days=1)).day
        days_elapsed = now.day
        days_remaining = days_in_month - days_elapsed

        # Safety check: if we're at or over budget, stop using credits
        if current_spend >= self.target_credits:
            logger.warning(f"At or over target spend: ${current_spend:.2f} >= ${self.target_credits:.2f}")
            return 0

        # Get target spend trajectory
        ideal_spend, target_daily_spend = self.get_target_spend_rate(
            current_spend, days_elapsed, days_in_month
        )

        # Calculate how far off we are from the ideal trajectory
        # Positive means we need to increase spending (behind schedule)
        # Negative means we need to decrease spending (ahead of schedule)
        trajectory_error = ideal_spend - current_spend
        
        # Normalize to percentage of total budget
        error_percentage = (trajectory_error / self.target_credits) * 100
        
        # Calculate base percentage from current daily spend vs target
        # This gives us a more dynamic base to work from
        if daily_spend_rate > 0 and target_daily_spend > 0:
            # Current percentage estimate based on spend rates
            current_percentage_estimate = 35
            base_percentage = min(100, max(0, current_percentage_estimate))
        else:
            base_percentage = 50.0
        
        # PID adjustment based on trajectory error
        # We want the PID to increase output when we're behind (positive error)
        # and decrease output when we're ahead (negative error)
        # Since PID tries to minimize error, we feed it negative error
        pid_adjustment = self.pid(-error_percentage)
        
        # Final percentage is base + adjustment
        adjustment = base_percentage + pid_adjustment
        
        # Clamp to valid range
        adjustment = max(0, min(100, adjustment))

        # Log for debugging and tuning
        logger.info(f"Day {days_elapsed}/{days_in_month}")
        logger.info(f"Current spend: ${current_spend:.2f}, Ideal: ${ideal_spend:.2f}")
        logger.info(f"Target daily spend: ${target_daily_spend:.2f}")
        logger.info(f"Daily spend rate: ${daily_spend_rate:.2f}")
        logger.info(f"Trajectory error: ${trajectory_error:.2f} ({error_percentage:.1f}%)")
        logger.info(f"Base: {base_percentage:.1f}%, PID adj: {pid_adjustment:.1f}%, Final: {adjustment:.1f}%")
        logger.info(f"P={self.pid.components[0]:.2f}, I={self.pid.components[1]:.2f}, D={self.pid.components[2]:.2f}")

        return adjustment

    def update_pid_tuning(self, Kp=None, Ki=None, Kd=None):
        """Adjust PID parameters if needed"""
        if Kp is not None:
            self.pid.Kp = Kp
        if Ki is not None:
            self.pid.Ki = Ki
        if Kd is not None:
            self.pid.Kd = Kd
        logger.info(f"Updated PID tuning: Kp={self.pid.Kp}, Ki={self.pid.Ki}, Kd={self.pid.Kd}")




# Production implementation
class AWSCreditController:
    """Production-ready controller with persistence and AWS integration"""

    def __init__(self, config_file='pid_state.json'):
        self.config_file = config_file
        self.optimizer = AWSCreditOptimizer()
        self.load_state()
        self.tenant_id = 'cc951ada-105f-40b1-8305-c65861490a90'
        self.api_base_url = f'https://api.ternary.app/analytics/query/load?tenant_id={self.tenant_id}'

    def _get_api_key(self):
        """Get the Ternary API key from environment variables"""
        ternary_api_key = os.getenv('TERNARY_API_KEY')
        if not ternary_api_key:
            raise ValueError("TERNARY_API_KEY environment variable is not set. Please create a .env file with your API key.")
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
            response = requests.post(self.api_base_url, headers=headers, json=payload)
            response.raise_for_status()
        
            response_json = response.json()
            
            if "response" in response_json and isinstance(response_json["response"], list):
                if response_json["response"]:
                    first_item = response_json["response"][0]
                    if "credits" in first_item:
                        return abs(first_item["credits"])
                    else:
                        raise ValueError("Response does not contain credits data")
                else:
                    return 0.0  # No spend data found
            else:
                raise ValueError("Invalid response format from API")
                
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred: {http_err}")
            logger.error(f"Response content: {response.text}")
            raise
        except requests.exceptions.ConnectionError as conn_err:
            logger.error(f"Connection error occurred: {conn_err}")
            raise
        except requests.exceptions.Timeout as timeout_err:
            logger.error(f"Timeout error occurred: {timeout_err}")
            raise
        except requests.exceptions.RequestException as req_err:
            logger.error(f"An unexpected error occurred: {req_err}")
            raise

    def get_current_spend(self, project_id="391835788720"):
        """
        Get the current spend for a specific project from the Ternary API.
        
        Args:
            project_id (str): The project ID to get spend for. Defaults to the main project ID.
        
        Returns:
            float: The current spend in credits (positive number)
        """
        # Get current UTC time
        now_utc = datetime.utcnow()
        end_date = now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        # Get start of current month
        start_of_month = datetime(now_utc.year, now_utc.month, 1)
        start_date = start_of_month.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        return self._query_ternary_api(start_date, end_date, project_id)

    def get_recent_spend_rate(self, project_id="391835788720"):
        """
        Calculate recent spend rate for the past 24 hours.
        
        Args:
            project_id (str): The project ID to get spend for. Defaults to the main project ID.
        
        Returns:
            float: The spend rate in credits per day (positive number)
        """
        # Get current UTC time and 24 hours ago
        now_utc = datetime.utcnow()
        end_date = now_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        # Calculate start date (24 hours ago)
        start_of_period = now_utc - timedelta(hours=24)
        start_date = start_of_period.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        # Get spend for last 24 hours and convert to daily rate
        credits_24h = self._query_ternary_api(start_date, end_date, project_id)
        return credits_24h * (24/24)  # Multiply by 24/24 for clarity of intent

    def load_state(self):
        """Load PID state from file to maintain continuity"""
        try:
            with open(self.config_file, 'r') as f:
                state = json.load(f)
                # Restore PID integral term for smooth continuation
                if 'integral' in state:
                    self.optimizer.pid._integral = state['integral']
                logger.info("Loaded previous PID state")
        except FileNotFoundError:
            logger.info("No previous state found, starting fresh")

    def save_state(self):
        """Save PID state for next run"""
        state = {
            'integral': self.optimizer.pid._integral,
            'last_update': datetime.now().isoformat(),
            'components': self.optimizer.pid.components
        }
        with open(self.config_file, 'w') as f:
            json.dump(state, f)

    def update_job_routing(self, percentage):
        """Update the CI/CD system with new routing percentage"""
        # In production, this would update your job routing configuration
        # Could be updating an environment variable, API call, or config file
        logger.info(f"Updating job routing to {percentage:.1f}% on LF AWS account")
        # Example: update_github_actions_variable('FREE_CREDIT_PERCENTAGE', percentage)
        pass

    def run_update_cycle(self):
        """Main update cycle - run this as a cron job"""
        try:
            # Get current metrics
            current_spend = self.get_current_spend()
            spend_rate = self.get_recent_spend_rate()

            # Calculate new percentage
            percentage = self.optimizer.calculate_percentage_split(
                current_spend, spend_rate
            )

            # Update routing
            self.update_job_routing(percentage)

            # Save state for next run
            self.save_state()

            # Log summary
            logger.info(f"Update complete: {percentage:.1f}% -> LF Rollout Percentage")

        except Exception as e:
            logger.error(f"Error in update cycle: {e}")
            # In production, send alert to ops team
    
def run_production_controller():
    """Run the production controller"""
    controller = AWSCreditController()
    controller.run_update_cycle()


if __name__ == "__main__":
    # Run the production controller
    run_production_controller()

    # Example of production usage:
    # controller = AWSCreditController()
    # controller.run_update_cycle()
