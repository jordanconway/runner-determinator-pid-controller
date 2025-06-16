# AWS Credit PID Controller

A Python-based PID (Proportional-Integral-Derivative) controller that automatically optimizes the distribution of CI/CD jobs between AWS accounts to maximize credit usage while staying within budget constraints.

## Overview

This system uses a PID controller to dynamically adjust the percentage of CI/CD jobs sent to the LF AWS account. It continuously monitors spending patterns and adjusts the job distribution to maintain an optimal spending trajectory throughout the month.

### Key Features

- **Real-time Spend Monitoring**: Tracks current spend and daily spend rates using the Ternary API
- **Modular API Integration**: Uses a centralized helper function for all Ternary API queries, reducing code duplication and improving maintainability
- **PID Control**: Uses a PID controller to make smooth, responsive adjustments to job distribution
- **Safety Features**:
  - 2% safety margin to prevent overspending
  - Output limits (0-100%) to prevent extreme adjustments
  - Automatic shutdown if budget is exceeded
- **Persistence**: Maintains PID state between runs for smooth operation
- **Comprehensive Logging & Error Handling**: Improved error logging and consistent error handling for all API calls

## TODO

- [ ] Implement automatic fetching of current LF runner percentage from [pytorch/test-infra#5132](https://github.com/pytorch/test-infra/issues/5132)
  - This will allow the PID controller to know the current baseline percentage before making adjustments
  - Need to parse the YAML configuration from the issue's first comment
  - Should update the baseline percentage whenever the issue is updated

## Installation

1. Clone the repository:
```bash
git clone https://github.com/pytorch/runner-determinator-pid-controller.git
cd runner-determinator-pid-controller
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

PID tuning parameters:
- `Kp`: Proportional gain (default: 2.0)
- `Ki`: Integral gain (default: 0.15)
- `Kd`: Derivative gain (default: 0.5)

## Usage

### Running the Controller

To run the controller in production mode:
```bash
python runner-determinator-pid-controller.py
```

The controller will:
1. Load previous state (if any)
2. Get current spend and spend rate
3. Calculate optimal job distribution
4. Update the routing configuration
5. Save state for the next run

### Logging

The system provides detailed logging including:
- Current spend vs. ideal spend
- Target daily spend rate
- Actual daily spend rate
- PID adjustments and components
- Final routing percentage

## How It Works

1. **Spend Monitoring**:
   - Tracks current month's spend
   - Calculates daily spend rate from the last 24 hours
   - Uses Ternary API for real-time spend data

2. **PID Control**:
   - Calculates ideal spend trajectory for the month
   - Compares current spend to ideal trajectory
   - Uses PID controller to adjust job distribution
   - Base percentage starts at 35% and is adjusted by PID output

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

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[Add your license information here]

## Support

[Add support contact information here] 