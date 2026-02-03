# Reminder Skill - Session 91

**Created:** 2026-02-03 (Session 91)
**Location:** `~/.claude/skills/reminder/`
**Status:** ✅ Working MVP

---

## What It Does

Simple reminder management across Claude sessions. Never forget follow-up tasks!

- ✅ Add reminders with due dates and priorities
- 📅 Auto-display on session start (shows today's and overdue)
- 💾 Persistent storage in `~/.claude/reminders.json`
- 🎯 Priority levels: high, medium, low
- 📝 Optional commands to execute

---

## Quick Start

### Add Reminders
```bash
/reminder add "Check Phase 6 verification" --date 2026-02-04 --priority high
/reminder add "Review PR" --priority medium
/reminder add "Run tests" --cmd "pytest tests/"
```

### View Reminders
```bash
/reminder list              # All active
/reminder list --today      # Today only
/reminder list --overdue    # Past due
/reminder show rem_001      # Details
```

### Manage Reminders
```bash
/reminder complete rem_001  # Mark done
/reminder delete rem_001    # Remove
```

---

## Current Reminders (Added for You)

### Tomorrow (2026-02-04)

1. **🔴 HIGH: Run Phase 6 verification script**
   - Command: `./bin/verify-phase6-deployment.sh`
   - Description: Verify model attribution and Phase 6 exports

2. **🔴 HIGH: Check model attribution for Feb 4 predictions**
   - Verify `model_file_name` is NOT NULL
   - Expected: `catboost_v9_feb_02_retrain.cbm`

3. **🟡 MEDIUM: Decide on backfilling 360 NULL predictions**
   - Feb 2-3 predictions missing model attribution
   - Decide if we should backfill

4. **🟡 MEDIUM: Consider Phase 2: Model Attribution Exporters**
   - If verification passes, plan Phase 2 implementation

### Future Reminders

5. **🟢 LOW: Review Phase 6 performance after 1 week** (2026-02-10)
   - Check API usage, hit rates, issues

6. **🔴 HIGH: Monthly model retraining - CatBoost V9** (2026-03-01)
   - Retrain with data through end of February
   - Use `ml/experiments/quick_retrain.py`

---

## Auto-Display on Session Start

When you start a new Claude session on 2026-02-04 or later, you'll automatically see:

```
============================================================
📋 REMINDERS
============================================================

📅 TODAY:
🔴 [rem_001] Run Phase 6 verification script
    📅 2026-02-04 (TODAY)

🔴 [rem_002] Check model attribution for Feb 4 predictions
    📅 2026-02-04 (TODAY)

🟡 [rem_003] Decide on backfilling 360 NULL predictions
    📅 2026-02-04 (TODAY)

🟡 [rem_004] Consider Phase 2: Model Attribution Exporters
    📅 2026-02-04 (TODAY)

============================================================
Use '/reminder list' to see all reminders
Use '/reminder complete <id>' to mark as done
============================================================
```

---

## Implementation Details

### Storage Location
`~/.claude/reminders.json`

### Data Structure
```json
{
  "reminders": [
    {
      "id": "rem_001",
      "title": "Run Phase 6 verification script",
      "description": "Verify model attribution...",
      "due_date": "2026-02-04",
      "priority": "high",
      "status": "active",
      "created_at": "2026-02-03T03:50:00Z",
      "completed_at": null,
      "command": "./bin/verify-phase6-deployment.sh"
    }
  ],
  "next_id": 7
}
```

### Files Created
```
~/.claude/skills/reminder/
├── skill.json          # Skill definition
├── reminder.py         # Python implementation
├── prompt.md          # Claude instructions
└── README.md          # Documentation
```

---

## Usage Examples

### Add Simple Reminder
```bash
/reminder add "Check deployment drift"
```

### Add with Date and Priority
```bash
/reminder add "Review logs" --date 2026-02-05 --priority high
```

### Add with Command
```bash
/reminder add "Run tests" --cmd "pytest tests/" --priority high
```

### View Details
```bash
/reminder show rem_001
```
Output:
```
🔴 [rem_001] Run Phase 6 verification script
    📅 2026-02-04 (2 days)
    Description: Verify model attribution...
    Command: ./bin/verify-phase6-deployment.sh
    Priority: high
    Status: active
```

### Complete Task
```bash
/reminder complete rem_001
```
Output:
```
✅ Marked rem_001 as complete
```

### Filter Views
```bash
/reminder list --today      # Only today's tasks
/reminder list --overdue    # Past due items
/reminder list --all        # Include completed
```

---

## Priority Symbols

- 🔴 **high** - Urgent, critical tasks
- 🟡 **medium** - Normal priority (default)
- 🟢 **low** - Nice to have, non-urgent

---

## Future Enhancements (v0.2+)

Potential additions for future sessions:

1. **Recurring reminders**
   ```bash
   /reminder add "Weekly health check" --recurring weekly
   ```

2. **Snooze functionality**
   ```bash
   /reminder snooze rem_001 --until tomorrow
   ```

3. **Categories/Tags**
   ```bash
   /reminder add "Fix bug" --tag deployment --tag urgent
   ```

4. **Team collaboration (Firestore)**
   - Share reminders across team
   - Assign to specific people

5. **Integration with handoff docs**
   - Auto-generate reminders from handoff TODOs
   - Link reminders to documentation

6. **Time support**
   ```bash
   /reminder add "Check logs" --date 2026-02-04 --time "07:30 ET"
   ```

7. **Reminder search**
   ```bash
   /reminder search "verification"
   ```

---

## Version History

### v0.1.0 (2026-02-03) - Initial MVP
- Basic CRUD operations (add, list, show, complete, delete)
- Due date tracking
- Priority levels (high, medium, low)
- Auto-display on session startup
- Command storage (optional)
- Persistent JSON storage

---

## Integration with Session Workflow

### Recommended Usage

1. **At session start:**
   - Review auto-displayed reminders
   - Prioritize what to work on

2. **During session:**
   - Add reminders for follow-up tasks
   - Mark completed items as done

3. **At session end:**
   - Add reminders for tomorrow
   - Review what's pending

### Example Workflow

```bash
# Session start - auto-displays today's reminders

# Work on task
./bin/verify-phase6-deployment.sh

# Mark complete
/reminder complete rem_001

# Add follow-up
/reminder add "Deploy Phase 2" --date 2026-02-05 --priority high

# Check what's left
/reminder list --today
```

---

## Tips

1. **Use descriptive titles** - "Check X" is better than "TODO"
2. **Set realistic due dates** - Don't over-schedule
3. **Use priorities wisely** - Not everything is high priority
4. **Add commands for quick execution** - One-click task execution
5. **Review weekly** - Clean up completed/outdated reminders
6. **Use descriptions** - Add context for future you

---

## Troubleshooting

### Reminders not showing on startup?
Check if auto_display is enabled in `~/.claude/skills/reminder/skill.json`

### Can't find reminder file?
```bash
ls -la ~/.claude/reminders.json
```

### Want to manually edit reminders?
```bash
vim ~/.claude/reminders.json
```
(Use caution - invalid JSON will break the skill)

### Reset all reminders?
```bash
rm ~/.claude/reminders.json
# Reminders will be recreated on next add
```

---

## Related Documentation

- Session 91 Deployment: `docs/09-handoff/2026-02-03-SESSION-91-DEPLOYMENT-COMPLETE.md`
- Session 92 Start: `docs/09-handoff/2026-02-04-SESSION-92-START-PROMPT.md`
- Skill README: `~/.claude/skills/reminder/README.md`

---

**The reminder skill is now active and ready to help you stay organized across Claude sessions!** 🎯
