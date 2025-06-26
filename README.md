# Runner Determinator PID Controller

A Python-based PID (Proportional-Integral-Derivative) controller that automatically optimizes the distribution of CI/CD jobs between AWS accounts to maximize credit usage while staying within budget constraints.

## Overview

This system uses a PID controller to dynamically adjust the percentage of CI/CD jobs sent to the LF AWS account. It continuously monitors spending patterns and adjusts the job distribution to maintain an optimal spending trajectory throughout the month.

### Key Features

- **Real-time Spend Monitoring**: Tracks current spend and daily spend rates using the Ternary API
- **Modular API Integration**: Uses a centralized helper function for all Ternary API queries, reducing code duplication and improving maintainability
- **Dynamic Rollout Percentage**: Automatically fetches the LF runner rollout percentage from the PyTorch test-infra issue comment and uses it in the PID controller logic
- **PID Control**: Uses a PID controller to make smooth, responsive adjustments to job distribution
- **Safety Features**:
  - 2% safety margin to prevent overspending
  - Output limits (0-100%) to prevent extreme adjustments
  - Automatic shutdown if budget is exceeded
- **Persistence**: Maintains PID state between runs for smooth operation
- **Comprehensive Logging & Error Handling**: Improved error logging and consistent error handling for all API calls. Logs are written to both the console and a rotating log file ('controller.log')
- **Code Quality**: Fully compliant with pylint standards, including proper line length limits, no trailing whitespace, and optimized control flow


## TODO

- [x] Implement automatic fetching of current LF runner percentage from [pytorch/test-infra#5132](https://github.com/pytorch/test-infra/issues/5132)
  - The PID controller now dynamically uses the latest rollout percentage from the issue comment
  - The YAML configuration is parsed from the issue's first comment
  - The baseline percentage is updated whenever the script runs
- [x] Code quality improvements and pylint compliance
- [ ] Implement automatic setting of LF runner percentage on GitHub
  - The script does not yet update the rollout percentage back to the GitHub issue

## Installation

1. Clone the repository:
```bash
git clone https://github.com/pytorch/runner-determinator-pid-controller.git
cd runner_determinator_pid_controller
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your Ternary API key:
```
TERNARY_API_KEY=your_api_key_here
```

## Configuration

The system can be configured through several parameters in the `AWSCreditOptimizer` class:

- `total_credits`: Total available credits (default: 500,000)
- `safety_margin`: Safety margin as a decimal (default: 0.02 for 2%)
- `update_interval`: How often to update in seconds (default: 3600 for hourly)

**Command Line Options:**
- `--days`: Number of days to look back for spend rate calculation (default: 1)

PID tuning parameters:
- `Kp`: Proportional gain (default: 2.0)
- `Ki`: Integral gain (default: 0.15)
- `Kd`: Derivative gain (default: 0.5)

## Usage

### Running the Controller

To run the controller in production mode:
```bash
python runner_determinator_pid_controller.py
```

To specify the number of days to look back for spend rate calculation:
```bash
# Use 7 days for spend rate calculation (default is 1 day)
python runner_determinator_pid_controller.py --days 7

# Use 30 days for spend rate calculation
python runner_determinator_pid_controller.py --days 30

# Show help and available options
python runner_determinator_pid_controller.py --help
```

The controller will:
1. Load previous state (if any)
2. Get current spend and spend rate (based on the specified number of days)
3. Calculate optimal job distribution
4. Update the routing configuration
5. Save state for the next run

### Logging

The system provides detailed logging including:
- Logs are written to both the console and a rotating log file (`controller.log`) in the project directory
- Current spend vs. ideal spend
- Target daily spend rate
- Actual daily spend rate (for the previous local calendar day)
- PID adjustments and components
- Final routing percentage

## How It Works

1. **Spend Monitoring**:
   - Tracks current month's spend
   - Calculates daily spend rate for the specified number of days (configurable via `--days` parameter, default: 1 day)
   - Uses Ternary API for real-time spend data

2. **PID Control**:
   - Calculates ideal spend trajectory for the month
   - Compares current spend to ideal trajectory
   - Uses PID controller to adjust job distribution
   - Base percentage is dynamically set from the rollout percentage fetched from the PyTorch test-infra issue, and is adjusted by PID output

3. **Safety Measures**:
   - Stops routing to LF AWS account if budget is exceeded
   - Maintains a 2% safety margin
   - Limits adjustments to prevent oscillation

## Tuning Guide

The PID controller can be tuned by adjusting the Kp, Ki, and Kd parameters:

- If spending is too slow to react: Increase Kp
- If there's persistent under/overspending: Increase Ki
- If there's oscillation or overshoot: Increase Kd
- If the system is unstable: Decrease all gains

Monitor the logs to see the effect of tuning changes:
- P component: Immediate response to error
- I component: Correction of accumulated error
- D component: Damping of oscillations

## Production Deployment

For production use:
1. Set up as a cron job to run hourly
2. Monitor logs for any issues
3. Adjust PID parameters based on observed behavior
4. Ensure the `.env` file is properly secured

## Code Quality

This project maintains high code quality standards:
- All code passes pylint checks
- Proper line length limits (79 characters)
- No trailing whitespace
- Optimized control flow
- Comprehensive error handling
- Clear and maintainable code structure

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Note**: Please ensure your code passes pylint checks before submitting a pull request.

## License

[Add your license information here]

## Support

[Add support contact information here] 