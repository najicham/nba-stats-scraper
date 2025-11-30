#!/usr/bin/env python3
"""
Test script for AWS SES email integration.
Verifies that AWS SES can send emails successfully.
"""

import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_environment():
    """
    Set up AWS SES environment variables.

    NOTE: Set these environment variables before running tests:
    - AWS_SES_ACCESS_KEY_ID
    - AWS_SES_SECRET_ACCESS_KEY
    - AWS_SES_REGION
    - AWS_SES_FROM_EMAIL
    - EMAIL_ALERTS_TO
    - EMAIL_CRITICAL_TO
    """
    # Check if credentials are already set
    if not os.environ.get('AWS_SES_ACCESS_KEY_ID'):
        logger.error("AWS_SES_ACCESS_KEY_ID not set. Please set environment variables before running tests.")
        logger.info("Required variables: AWS_SES_ACCESS_KEY_ID, AWS_SES_SECRET_ACCESS_KEY, AWS_SES_REGION, AWS_SES_FROM_EMAIL, EMAIL_ALERTS_TO")
        sys.exit(1)

    # Set defaults for non-sensitive values if not provided
    os.environ.setdefault('AWS_SES_REGION', 'us-west-2')
    os.environ.setdefault('AWS_SES_FROM_EMAIL', 'alert@989.ninja')

    logger.info("Environment variables configured")


def test_ses_direct():
    """Test AWS SES directly using boto3."""
    import boto3
    from botocore.exceptions import ClientError

    logger.info("Testing direct boto3 SES connection...")

    ses_client = boto3.client(
        'ses',
        region_name=os.environ['AWS_SES_REGION'],
        aws_access_key_id=os.environ['AWS_SES_ACCESS_KEY_ID'],
        aws_secret_access_key=os.environ['AWS_SES_SECRET_ACCESS_KEY']
    )

    # Test: Get send quota (doesn't send email, just tests auth)
    try:
        quota = ses_client.get_send_quota()
        logger.info(f"SES Auth Success! Send quota: {quota['Max24HourSend']}, Used: {quota['SentLast24Hours']}")
        return True
    except ClientError as e:
        logger.error(f"SES Auth Failed: {e.response['Error']['Message']}")
        return False


def test_email_alerter_ses():
    """Test the EmailAlerterSES class."""
    logger.info("Testing EmailAlerterSES class...")

    try:
        from shared.utils.email_alerting_ses import EmailAlerterSES

        alerter = EmailAlerterSES()
        logger.info("EmailAlerterSES initialized successfully")

        # Send a test error alert
        success = alerter.send_error_alert(
            error_message="This is a test error from the SES integration test",
            error_details={
                "test_type": "SES Integration Test",
                "timestamp": "2025-11-29",
                "status": "Testing"
            },
            processor_name="SES Test Script"
        )

        if success:
            logger.info("Test email sent successfully via EmailAlerterSES!")
        else:
            logger.warning("Email send returned False - check logs above")

        return success

    except Exception as e:
        logger.error(f"EmailAlerterSES test failed: {e}")
        return False


def test_notification_system():
    """Test the notification system with SES integration."""
    logger.info("Testing NotificationRouter with SES...")

    try:
        # Reset any cached router
        from shared.utils.notification_system import reset_router, notify_error
        reset_router()

        # Send test notification
        result = notify_error(
            title="SES Integration Test",
            message="This is a test notification via the NotificationRouter",
            details={
                "test_type": "NotificationRouter Test",
                "backend": "AWS SES"
            },
            processor_name="Notification System Test"
        )

        logger.info(f"NotificationRouter result: {result}")
        return bool(result.get('email'))

    except Exception as e:
        logger.error(f"NotificationRouter test failed: {e}")
        return False


def main():
    """Run all SES tests."""
    print("=" * 60)
    print("AWS SES Email Integration Test")
    print("=" * 60)

    # Setup
    setup_environment()

    results = {}

    # Test 1: Direct SES auth
    print("\n[1/3] Testing direct SES connection...")
    results['ses_auth'] = test_ses_direct()

    # Test 2: EmailAlerterSES class
    print("\n[2/3] Testing EmailAlerterSES class...")
    results['email_alerter'] = test_email_alerter_ses()

    # Test 3: NotificationRouter
    print("\n[3/3] Testing NotificationRouter integration...")
    results['notification_router'] = test_notification_system()

    # Summary
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")

    all_passed = all(results.values())
    print("\n" + "=" * 60)
    if all_passed:
        print("All tests PASSED! Check your email for test messages.")
    else:
        print("Some tests FAILED. Check the logs above for details.")
        print("\nNote: If in sandbox mode, ensure nchammas@gmail.com is verified in AWS SES.")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
