#!/usr/bin/env python3
"""
File: monitoring/scrapers/freshness/utils/alert_formatter.py

Formats freshness check results for Slack and Email notifications.
Creates human-readable messages and structured data for alerts.
"""

import logging
from typing import List, Dict
from datetime import datetime

from monitoring.scrapers.freshness.core.freshness_checker import CheckResult, CheckStatus

logger = logging.getLogger(__name__)


class AlertFormatter:
    """
    Formats freshness check results into alerts.
    
    Creates messages for Slack and Email that are:
    - Clear and actionable
    - Include relevant context
    - Easy to scan and understand
    """
    
    @staticmethod
    def format_for_notification(
        results: List[CheckResult],
        summary: Dict,
        season_info: Dict
    ) -> Dict:
        """
        Format check results for notification system.
        
        Args:
            results: List of check results
            summary: Summary statistics
            season_info: Current season information
        
        Returns:
            Dict with formatted message and details
        """
        # Separate results by status
        critical = [r for r in results if r.status == CheckStatus.CRITICAL]
        warnings = [r for r in results if r.status == CheckStatus.WARNING]
        errors = [r for r in results if r.status == CheckStatus.ERROR]
        
        # Determine overall severity
        if critical or errors:
            severity = "critical"
            title = "🔴 Scraper Freshness Issues Detected"
        elif warnings:
            severity = "warning"
            title = "🟡 Scraper Freshness Warnings"
        else:
            severity = "info"
            title = "✅ All Scrapers Fresh"
        
        # Build message
        message_lines = []
        
        # Add summary
        message_lines.append(f"**Season:** {season_info.get('season_label')} - {season_info.get('current_phase')}")
        message_lines.append(f"**Health Score:** {summary.get('health_score', 0)}%")
        message_lines.append(f"**Checked:** {summary.get('total_checked', 0)} scrapers")
        message_lines.append("")
        
        # Add status breakdown
        message_lines.append(f"✅ OK: {summary.get('ok', 0)}")
        message_lines.append(f"🟡 Warnings: {summary.get('warning', 0)}")
        message_lines.append(f"🔴 Critical: {summary.get('critical', 0)}")
        message_lines.append(f"❌ Errors: {summary.get('error', 0)}")
        message_lines.append(f"⏭️  Skipped: {summary.get('skipped', 0)}")
        message_lines.append("")
        
        # Add critical issues
        if critical:
            message_lines.append("**🔴 CRITICAL ISSUES:**")
            for result in critical:
                message_lines.append(
                    f"• **{result.scraper_name}**: {result.message}"
                )
            message_lines.append("")
        
        # Add errors
        if errors:
            message_lines.append("**❌ ERRORS:**")
            for result in errors:
                message_lines.append(
                    f"• **{result.scraper_name}**: {result.message}"
                )
            message_lines.append("")
        
        # Add warnings
        if warnings:
            message_lines.append("**🟡 WARNINGS:**")
            for result in warnings[:5]:  # Limit to first 5 warnings
                message_lines.append(
                    f"• **{result.scraper_name}**: {result.message}"
                )
            if len(warnings) > 5:
                message_lines.append(f"• _...and {len(warnings) - 5} more warnings_")
            message_lines.append("")
        
        # Build details dictionary
        details = {
            'summary': summary,
            'season_info': season_info,
            'critical_count': len(critical),
            'warning_count': len(warnings),
            'error_count': len(errors),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Add critical scraper details
        if critical:
            details['critical_scrapers'] = [
                {
                    'name': r.scraper_name,
                    'message': r.message,
                    'details': r.details
                }
                for r in critical
            ]
        
        return {
            'title': title,
            'message': '\n'.join(message_lines),
            'severity': severity,
            'details': details
        }
    
    @staticmethod
    def format_slack_table(results: List[CheckResult]) -> str:
        """
        Format results as a Slack-friendly table.
        
        Args:
            results: List of check results
        
        Returns:
            Formatted table string
        """
        lines = []
        lines.append("```")
        lines.append(f"{'Scraper':<30} {'Status':<10} {'Age':<8} {'Message':<40}")
        lines.append("-" * 90)
        
        for result in results:
            if result.status == CheckStatus.SKIPPED:
                continue
            
            # Get status emoji
            if result.status == CheckStatus.OK:
                status = "✅ OK"
            elif result.status == CheckStatus.WARNING:
                status = "🟡 WARN"
            elif result.status == CheckStatus.CRITICAL:
                status = "🔴 CRIT"
            else:
                status = "❌ ERR"
            
            # Get age
            age = result.details.get('file_age_hours', 0)
            age_str = f"{age:.1f}h" if age else "N/A"
            
            # Truncate message
            message = result.message[:38] + ".." if len(result.message) > 40 else result.message
            
            # Truncate scraper name
            name = result.scraper_name[:28] + ".." if len(result.scraper_name) > 30 else result.scraper_name
            
            lines.append(f"{name:<30} {status:<10} {age_str:<8} {message:<40}")
        
        lines.append("```")
        return '\n'.join(lines)
    
    @staticmethod
    def format_email_html(
        results: List[CheckResult],
        summary: Dict,
        season_info: Dict
    ) -> str:
        """
        Format results as HTML for email.
        
        Args:
            results: List of check results
            summary: Summary statistics
            season_info: Current season information
        
        Returns:
            HTML string
        """
        html_parts = []
        
        # Header
        html_parts.append("<html><body style='font-family: Arial, sans-serif;'>")
        html_parts.append("<h2>Scraper Freshness Monitoring Report</h2>")
        
        # Summary
        html_parts.append("<div style='background-color: #f0f0f0; padding: 15px; margin: 10px 0;'>")
        html_parts.append(f"<p><strong>Season:</strong> {season_info.get('season_label')} - {season_info.get('current_phase')}</p>")
        html_parts.append(f"<p><strong>Health Score:</strong> {summary.get('health_score', 0)}%</p>")
        html_parts.append(f"<p><strong>Timestamp:</strong> {summary.get('timestamp', 'N/A')}</p>")
        html_parts.append("</div>")
        
        # Status counts
        html_parts.append("<h3>Status Summary</h3>")
        html_parts.append("<table style='border-collapse: collapse; width: 100%;'>")
        html_parts.append("<tr style='background-color: #e0e0e0;'>")
        html_parts.append("<th style='padding: 8px; border: 1px solid #ddd;'>Status</th>")
        html_parts.append("<th style='padding: 8px; border: 1px solid #ddd;'>Count</th>")
        html_parts.append("</tr>")
        
        status_items = [
            ("✅ OK", summary.get('ok', 0), '#d4edda'),
            ("🟡 Warnings", summary.get('warning', 0), '#fff3cd'),
            ("🔴 Critical", summary.get('critical', 0), '#f8d7da'),
            ("❌ Errors", summary.get('error', 0), '#f8d7da'),
            ("⏭️ Skipped", summary.get('skipped', 0), '#f0f0f0')
        ]
        
        for label, count, color in status_items:
            html_parts.append(f"<tr style='background-color: {color};'>")
            html_parts.append(f"<td style='padding: 8px; border: 1px solid #ddd;'>{label}</td>")
            html_parts.append(f"<td style='padding: 8px; border: 1px solid #ddd;'>{count}</td>")
            html_parts.append("</tr>")
        
        html_parts.append("</table>")
        
        # Detailed results (only issues)
        issues = [r for r in results if r.status in [CheckStatus.CRITICAL, CheckStatus.WARNING, CheckStatus.ERROR]]
        
        if issues:
            html_parts.append("<h3>Issues Requiring Attention</h3>")
            html_parts.append("<table style='border-collapse: collapse; width: 100%;'>")
            html_parts.append("<tr style='background-color: #e0e0e0;'>")
            html_parts.append("<th style='padding: 8px; border: 1px solid #ddd;'>Scraper</th>")
            html_parts.append("<th style='padding: 8px; border: 1px solid #ddd;'>Status</th>")
            html_parts.append("<th style='padding: 8px; border: 1px solid #ddd;'>Message</th>")
            html_parts.append("<th style='padding: 8px; border: 1px solid #ddd;'>Age</th>")
            html_parts.append("</tr>")
            
            for result in issues:
                # Determine row color
                if result.status == CheckStatus.CRITICAL:
                    row_color = '#f8d7da'
                    status_label = '🔴 CRITICAL'
                elif result.status == CheckStatus.WARNING:
                    row_color = '#fff3cd'
                    status_label = '🟡 WARNING'
                else:
                    row_color = '#f8d7da'
                    status_label = '❌ ERROR'
                
                age = result.details.get('file_age_hours', 0)
                age_str = f"{age:.1f}h" if age else "N/A"
                
                html_parts.append(f"<tr style='background-color: {row_color};'>")
                html_parts.append(f"<td style='padding: 8px; border: 1px solid #ddd;'>{result.scraper_name}</td>")
                html_parts.append(f"<td style='padding: 8px; border: 1px solid #ddd;'>{status_label}</td>")
                html_parts.append(f"<td style='padding: 8px; border: 1px solid #ddd;'>{result.message}</td>")
                html_parts.append(f"<td style='padding: 8px; border: 1px solid #ddd;'>{age_str}</td>")
                html_parts.append("</tr>")
            
            html_parts.append("</table>")
        else:
            html_parts.append("<p style='color: green;'>✅ All scrapers are healthy!</p>")
        
        # Footer
        html_parts.append("<p style='margin-top: 20px; color: #888; font-size: 12px;'>")
        html_parts.append("This is an automated report from the NBA Scraper Freshness Monitoring System.")
        html_parts.append("</p>")
        html_parts.append("</body></html>")
        
        return ''.join(html_parts)
    
    @staticmethod
    def should_send_alert(
        results: List[CheckResult],
        min_severity: str = "warning"
    ) -> bool:
        """
        Determine if an alert should be sent based on results.
        
        Args:
            results: List of check results
            min_severity: Minimum severity to trigger alert ('warning', 'critical')
        
        Returns:
            True if alert should be sent
        """
        if min_severity == "critical":
            return any(
                r.status in [CheckStatus.CRITICAL, CheckStatus.ERROR]
                for r in results
            )
        elif min_severity == "warning":
            return any(
                r.status in [CheckStatus.WARNING, CheckStatus.CRITICAL, CheckStatus.ERROR]
                for r in results
            )
        else:
            return True
