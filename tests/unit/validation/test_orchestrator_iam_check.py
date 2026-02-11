"""
Unit tests for Orchestrator IAM Permission Check

Tests the IAM validation logic added in Session 205 that ensures all 4 orchestrators
have the required `roles/run.invoker` permission for Pub/Sub to invoke them.

Reference: .claude/skills/validate-daily/SKILL.md - Check 5: Orchestrator IAM Permissions
"""

import pytest
import json
import subprocess
from unittest.mock import patch, MagicMock, call
from typing import Dict, List


class TestOrchestratorIAMCheck:
    """
    Tests for orchestrator IAM permission validation.

    The validation script checks that all 4 phase transition orchestrators have
    the required IAM permissions to be invoked by Pub/Sub. This prevents the
    silent failure discovered in Session 205 where orchestrators couldn't be
    invoked due to missing permissions.
    """

    ORCHESTRATORS = [
        'phase2-to-phase3-orchestrator',
        'phase3-to-phase4-orchestrator',
        'phase4-to-phase5-orchestrator',
        'phase5-to-phase6-orchestrator'
    ]

    SERVICE_ACCOUNT = '756957797294-compute@developer.gserviceaccount.com'
    PROJECT = 'nba-props-platform'
    REGION = 'us-west2'

    @staticmethod
    def mock_iam_policy_success(orchestrator: str) -> str:
        """Generate a successful IAM policy JSON response."""
        return json.dumps({
            "bindings": [
                {
                    "members": [
                        f"serviceAccount:{TestOrchestratorIAMCheck.SERVICE_ACCOUNT}"
                    ],
                    "role": "roles/run.invoker"
                }
            ],
            "etag": "BwYZ8K1234A=",
            "version": 1
        })

    @staticmethod
    def mock_iam_policy_missing_permission(orchestrator: str) -> str:
        """Generate IAM policy JSON without run.invoker permission."""
        return json.dumps({
            "bindings": [
                {
                    "members": [
                        f"serviceAccount:{TestOrchestratorIAMCheck.SERVICE_ACCOUNT}"
                    ],
                    "role": "roles/viewer"
                }
            ],
            "etag": "BwYZ8K1234A=",
            "version": 1
        })

    @staticmethod
    def mock_iam_policy_wrong_service_account(orchestrator: str) -> str:
        """Generate IAM policy JSON with run.invoker but wrong service account."""
        return json.dumps({
            "bindings": [
                {
                    "members": [
                        "serviceAccount:wrong-account@developer.gserviceaccount.com"
                    ],
                    "role": "roles/run.invoker"
                }
            ],
            "etag": "BwYZ8K1234A=",
            "version": 1
        })

    @staticmethod
    def mock_iam_policy_empty() -> str:
        """Generate empty IAM policy JSON."""
        return json.dumps({
            "bindings": [],
            "etag": "BwYZ8K1234A=",
            "version": 1
        })

    @staticmethod
    def create_subprocess_result(returncode: int, stdout: str, stderr: str = "") -> MagicMock:
        """Helper to create a mock subprocess.CompletedProcess."""
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    def test_all_orchestrators_have_correct_permissions(self):
        """
        Test success scenario: All 4 orchestrators have correct IAM permissions.

        Expected:
        - Exit code 0 (success)
        - All orchestrators show "✅ IAM permissions OK"
        - No missing permissions reported
        """
        # Mock successful IAM policy responses for all orchestrators
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = self.create_subprocess_result(
                returncode=0,
                stdout=self.mock_iam_policy_success("dummy")
            )

            # Execute the validation logic directly
            exit_code, output = self._run_validation_script(mock_run)

            # Verify success
            assert exit_code == 0, f"Expected success but got exit code {exit_code}"
            assert "✅ All orchestrators have correct IAM permissions" in output

            # Verify all orchestrators were checked
            for orch in self.ORCHESTRATORS:
                assert f"✅ {orch}: IAM permissions OK" in output

            # Verify no critical errors
            assert "🔴 P0 CRITICAL" not in output
            assert "MISSING roles/run.invoker" not in output

    def test_single_orchestrator_missing_permission(self):
        """
        Test failure scenario: One orchestrator missing IAM permission.

        Expected:
        - Exit code 1 (failure)
        - P0 CRITICAL alert
        - Affected orchestrator identified
        - Fix command provided
        """
        with patch('subprocess.run') as mock_run:
            def side_effect(*args, **kwargs):
                # Check which orchestrator is being queried
                cmd = args[0]
                if 'phase2-to-phase3-orchestrator' in cmd:
                    # Missing permission for phase2-to-phase3
                    return self.create_subprocess_result(
                        returncode=0,
                        stdout=self.mock_iam_policy_missing_permission("phase2-to-phase3-orchestrator")
                    )
                else:
                    # Success for others
                    return self.create_subprocess_result(
                        returncode=0,
                        stdout=self.mock_iam_policy_success("dummy")
                    )

            mock_run.side_effect = side_effect

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify failure
            assert result.returncode == 1, f"Expected failure but got exit code {result.returncode}"

            # Verify error messaging
            assert "🔴 P0 CRITICAL" in result.stdout
            assert "1 orchestrator(s) missing IAM permissions" in result.stdout
            assert "phase2-to-phase3-orchestrator" in result.stdout

            # Verify fix command is provided
            assert "Fix command:" in result.stdout
            assert "gcloud run services add-iam-policy-binding" in result.stdout
            assert "--role='roles/run.invoker'" in result.stdout

            # Verify impact description
            assert "Pub/Sub cannot invoke these orchestrators" in result.stdout

    def test_all_orchestrators_missing_permissions(self):
        """
        Test failure scenario: All orchestrators missing IAM permissions.

        This simulates the actual Session 205 bug where all 4 orchestrators
        lacked the required permission.

        Expected:
        - Exit code 1 (failure)
        - P0 CRITICAL alert
        - All 4 orchestrators identified
        - Fix commands for all orchestrators
        """
        with patch('subprocess.run') as mock_run:
            # All orchestrators return empty IAM policy
            mock_run.return_value = self.create_subprocess_result(
                returncode=0,
                stdout=self.mock_iam_policy_empty()
            )

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify failure
            assert result.returncode == 1

            # Verify all orchestrators are identified as missing
            assert "4 orchestrator(s) missing IAM permissions" in result.stdout
            for orch in self.ORCHESTRATORS:
                assert orch in result.stdout
                assert f"🔴 {orch}: MISSING roles/run.invoker permission!" in result.stdout

            # Verify fix commands for all orchestrators
            assert result.stdout.count("gcloud run services add-iam-policy-binding") == 4

    def test_gcloud_command_fails(self):
        """
        Test failure scenario: gcloud command returns non-zero exit code.

        This could happen if:
        - Service doesn't exist
        - Insufficient permissions to query IAM
        - Network issues

        Expected:
        - Exit code 1 (failure)
        - Error reported for affected orchestrator
        - Other orchestrators still checked
        """
        with patch('subprocess.run') as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if 'phase3-to-phase4-orchestrator' in cmd:
                    # gcloud command fails for phase3-to-phase4
                    return self.create_subprocess_result(
                        returncode=1,
                        stdout="",
                        stderr="ERROR: Service not found"
                    )
                else:
                    # Success for others
                    return self.create_subprocess_result(
                        returncode=0,
                        stdout=self.mock_iam_policy_success("dummy")
                    )

            mock_run.side_effect = side_effect

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify failure
            assert result.returncode == 1

            # Verify error reported for failed orchestrator
            assert "❌ phase3-to-phase4-orchestrator: Failed to get IAM policy" in result.stdout

            # Verify other orchestrators show success
            assert "✅ phase2-to-phase3-orchestrator: IAM permissions OK" in result.stdout
            assert "✅ phase4-to-phase5-orchestrator: IAM permissions OK" in result.stdout
            assert "✅ phase5-to-phase6-orchestrator: IAM permissions OK" in result.stdout

    def test_timeout_error(self):
        """
        Test failure scenario: gcloud command times out.

        Expected:
        - Exit code 1 (failure)
        - Timeout exception caught and reported
        - Orchestrator marked as missing permission
        """
        with patch('subprocess.run') as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                if 'phase4-to-phase5-orchestrator' in cmd:
                    # Simulate timeout
                    raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)
                else:
                    # Success for others
                    return self.create_subprocess_result(
                        returncode=0,
                        stdout=self.mock_iam_policy_success("dummy")
                    )

            mock_run.side_effect = side_effect

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify failure
            assert result.returncode == 1

            # Verify timeout error reported
            assert "❌ phase4-to-phase5-orchestrator: Error checking IAM" in result.stdout
            assert "phase4-to-phase5-orchestrator" in result.stdout

    def test_wrong_service_account_has_permission(self):
        """
        Test failure scenario: roles/run.invoker exists but for wrong service account.

        Expected:
        - Exit code 1 (failure)
        - Orchestrator marked as missing permission
        - Both role and service account must match
        """
        with patch('subprocess.run') as mock_run:
            # Return IAM policy with correct role but wrong service account
            mock_run.return_value = self.create_subprocess_result(
                returncode=0,
                stdout=self.mock_iam_policy_wrong_service_account("dummy")
            )

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify failure
            assert result.returncode == 1

            # All orchestrators should be marked as missing (wrong service account)
            for orch in self.ORCHESTRATORS:
                assert f"🔴 {orch}: MISSING roles/run.invoker permission!" in result.stdout

    def test_mixed_permissions(self):
        """
        Test failure scenario: Mix of orchestrators with/without permissions.

        Real-world scenario where some orchestrators were fixed but others weren't.

        Expected:
        - Exit code 1 (failure)
        - Only affected orchestrators in missing list
        - Fix commands only for affected orchestrators
        """
        with patch('subprocess.run') as mock_run:
            def side_effect(*args, **kwargs):
                cmd = args[0]
                # phase2-to-phase3: OK
                # phase3-to-phase4: MISSING
                # phase4-to-phase5: OK
                # phase5-to-phase6: MISSING
                if 'phase3-to-phase4-orchestrator' in cmd or 'phase5-to-phase6-orchestrator' in cmd:
                    return self.create_subprocess_result(
                        returncode=0,
                        stdout=self.mock_iam_policy_empty()
                    )
                else:
                    return self.create_subprocess_result(
                        returncode=0,
                        stdout=self.mock_iam_policy_success("dummy")
                    )

            mock_run.side_effect = side_effect

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify failure
            assert result.returncode == 1

            # Verify count
            assert "2 orchestrator(s) missing IAM permissions" in result.stdout

            # Verify correct orchestrators identified
            assert "phase3-to-phase4-orchestrator" in result.stdout
            assert "phase5-to-phase6-orchestrator" in result.stdout

            # Verify successful orchestrators shown as OK
            assert "✅ phase2-to-phase3-orchestrator: IAM permissions OK" in result.stdout
            assert "✅ phase4-to-phase5-orchestrator: IAM permissions OK" in result.stdout

    def test_json_parsing_error(self):
        """
        Test failure scenario: gcloud returns malformed JSON.

        Expected:
        - Exit code 1 (failure)
        - Error caught and reported
        - Orchestrator marked as missing permission
        """
        with patch('subprocess.run') as mock_run:
            # Return malformed JSON
            mock_run.return_value = self.create_subprocess_result(
                returncode=0,
                stdout="{ invalid json"
            )

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify failure
            assert result.returncode == 1

            # All orchestrators should fail to parse
            for orch in self.ORCHESTRATORS:
                # The script checks for role and service account in stdout,
                # so invalid JSON will be treated as missing permission
                assert f"🔴 {orch}: MISSING roles/run.invoker permission!" in result.stdout

    def test_gcloud_command_structure(self):
        """
        Test that the script calls gcloud with correct parameters.

        Verifies:
        - Correct gcloud command structure
        - All required flags present
        - Correct project and region
        - JSON output format
        """
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = self.create_subprocess_result(
                returncode=0,
                stdout=self.mock_iam_policy_success("dummy")
            )

            # Execute the validation script
            subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify gcloud was called for each orchestrator
            assert mock_run.call_count == 4

            # Verify command structure for first call
            first_call_args = mock_run.call_args_list[0][0][0]
            assert 'gcloud' in first_call_args
            assert 'run' in first_call_args
            assert 'services' in first_call_args
            assert 'get-iam-policy' in first_call_args
            assert '--region=us-west2' in first_call_args
            assert '--project=nba-props-platform' in first_call_args
            assert '--format=json' in first_call_args

    def test_error_message_includes_impact_and_fix(self):
        """
        Test that error messages are helpful and actionable.

        Verifies:
        - Clear severity (P0 CRITICAL)
        - Impact description
        - Symptoms
        - Actionable fix command
        - Correct service account in fix command
        """
        with patch('subprocess.run') as mock_run:
            # All missing permissions
            mock_run.return_value = self.create_subprocess_result(
                returncode=0,
                stdout=self.mock_iam_policy_empty()
            )

            # Execute the validation script
            result = subprocess.run(
                ['python3', '-c', self._get_validation_script()],
                capture_output=True,
                text=True,
                timeout=30
            )

            # Verify comprehensive error message
            assert "🔴 P0 CRITICAL" in result.stdout
            assert "Impact: Pub/Sub cannot invoke these orchestrators" in result.stdout
            assert "Pipeline will stall when processors complete" in result.stdout

            # Verify fix commands are complete
            assert "Fix command:" in result.stdout
            assert f"--member='serviceAccount:{self.SERVICE_ACCOUNT}'" in result.stdout
            assert "--role='roles/run.invoker'" in result.stdout
            assert f"--project={self.PROJECT}" in result.stdout

    @staticmethod
    def _get_validation_script() -> str:
        """
        Return the actual validation script from SKILL.md.

        This is the script that runs in production as part of /validate-daily.
        """
        return """
import subprocess
import sys

orchestrators = [
    'phase2-to-phase3-orchestrator',
    'phase3-to-phase4-orchestrator',
    'phase4-to-phase5-orchestrator',
    'phase5-to-phase6-orchestrator'
]

missing_permissions = []
service_account = '756957797294-compute@developer.gserviceaccount.com'

print("\\n=== Orchestrator IAM Permission Check ===\\n")

for orch in orchestrators:
    try:
        result = subprocess.run(
            ['gcloud', 'run', 'services', 'get-iam-policy', orch,
             '--region=us-west2', '--project=nba-props-platform',
             '--format=json'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print(f"  ❌ {orch}: Failed to get IAM policy")
            missing_permissions.append(orch)
            continue

        # Check if roles/run.invoker exists for service account
        if 'roles/run.invoker' in result.stdout and service_account in result.stdout:
            print(f"  ✅ {orch}: IAM permissions OK")
        else:
            print(f"  🔴 {orch}: MISSING roles/run.invoker permission!")
            missing_permissions.append(orch)

    except Exception as e:
        print(f"  ❌ {orch}: Error checking IAM - {e}")
        missing_permissions.append(orch)

if missing_permissions:
    print(f"\\n🔴 P0 CRITICAL: {len(missing_permissions)} orchestrator(s) missing IAM permissions!")
    print(f"   Affected: {', '.join(missing_permissions)}")
    print(f"\\n   Impact: Pub/Sub cannot invoke these orchestrators")
    print(f"           Pipeline will stall when processors complete")
    print(f"\\n   Fix command:")
    for orch in missing_permissions:
        print(f"   gcloud run services add-iam-policy-binding {orch} \\\\")
        print(f"     --region=us-west2 \\\\")
        print(f"     --member='serviceAccount:{service_account}' \\\\")
        print(f"     --role='roles/run.invoker' \\\\")
        print(f"     --project=nba-props-platform")
        print()
    sys.exit(1)
else:
    print(f"\\n✅ All orchestrators have correct IAM permissions")
    sys.exit(0)
"""


class TestOrchestratorIAMCheckIntegration:
    """
    Integration tests that verify the script works with actual gcloud commands.

    These tests are skipped by default and only run when explicitly requested
    with: pytest -m integration
    """

    @pytest.mark.integration
    @pytest.mark.skipif(True, reason="Requires actual gcloud authentication")
    def test_real_gcloud_command(self):
        """
        Test with real gcloud command (requires authentication).

        This test is skipped by default. To run:
        1. Ensure gcloud is authenticated: gcloud auth login
        2. Run: pytest tests/unit/validation/test_orchestrator_iam_check.py -v -m integration
        """
        # Execute the actual validation script
        result = subprocess.run(
            ['python3', '-c', TestOrchestratorIAMCheck._get_validation_script()],
            capture_output=True,
            text=True,
            timeout=60
        )

        # Just verify it doesn't crash
        assert result.returncode in [0, 1]
        assert "=== Orchestrator IAM Permission Check ===" in result.stdout
