# Documentation Templates

**Purpose:** Standardized templates for creating consistent documentation
**Last Updated:** 2025-11-23

---

## What's Here

This directory contains **documentation templates** that ensure consistency across processor documentation, design docs, and other technical documentation.

**Use these when:**
- Creating documentation for a new processor
- Documenting a new feature or system
- Ensuring consistent structure across docs
- Onboarding new team members (template shows expected content)

---

## Available Templates

### [processor-reference-card-template.md](processor-reference-card-template.md)

**Type:** Processor Quick Reference Card
**Purpose:** One-page summary of a processor's essential information
**Target Audience:** Operators, developers, on-call engineers

#### What It Includes

Complete template with 9 sections:

1. **Essential Facts** - Type, schedule, duration, priority, status
2. **Code & Tests** - File locations, sizes, test coverage
3. **Dependencies** - Upstream sources and downstream consumers
4. **What It Does** - Primary function, key output, value proposition
5. **Key Metrics** - Formulas, ranges, examples
6. **Processing Logic** - High-level flow
7. **Common Issues** - Known problems and solutions
8. **Monitoring** - Health check queries, alerts, dashboards
9. **Related Docs** - Links to detailed documentation

#### How to Use

1. **Copy the template** to `processor-cards/` directory
2. **Rename** to match processor name (e.g., `phase3-player-game-summary.md`)
3. **Fill in each section** - Replace all `[placeholders]` with actual values
4. **Verify against code** - Ensure everything matches implementation
5. **Mark as verified** - Update the "Verified" status at top
6. **Link from main docs** - Add to processor-cards/README.md

#### Example Usage

```bash
# Copy template
cp docs/templates/processor-reference-card-template.md \
   docs/processor-cards/phase3-new-processor.md

# Edit with your processor details
# Replace [Processor Name] → "New Processor"
# Replace [Date] → "2025-11-23"
# Fill in all sections...
```

#### Template Sections Explained

**Essential Facts**
- Quick reference table for operators
- Include schedule, duration, priority
- Mark status (Production Ready vs In Development)

**Dependencies (v4.0 Tracking)**
- Shows data flow in/out
- Mark CRITICAL vs OPTIONAL sources
- List downstream consumers

**Key Metrics Calculated**
- Document formulas with code examples
- Include ranges and concrete examples
- Helps operators understand output

**Common Issues**
- Document known problems BEFORE they become incidents
- Include symptoms, diagnosis, resolution
- Links to detailed troubleshooting

**Monitoring**
- Ready-to-run health check queries
- Alert conditions and thresholds
- Links to Grafana dashboards

#### Existing Examples

See these completed processor cards:
- [phase3-player-game-summary.md](../processor-cards/phase3-player-game-summary.md)
- [phase3-team-defense-game-summary.md](../processor-cards/phase3-team-defense-game-summary.md)
- [phase4-ml-feature-store-v2.md](../processor-cards/phase4-ml-feature-store-v2.md)
- [phase5-prediction-coordinator.md](../processor-cards/phase5-prediction-coordinator.md)

---

## Template Guidelines

### When Creating Templates

**Good templates:**
- ✅ Have clear section headers
- ✅ Use `[placeholders]` for values to replace
- ✅ Include examples showing expected content
- ✅ Explain why each section matters
- ✅ Are comprehensive but not overwhelming

**Avoid:**
- ❌ Too much boilerplate (keep it focused)
- ❌ Unclear placeholders (be specific about what to fill in)
- ❌ Missing sections (better to have placeholder than omit)
- ❌ No examples (show what good looks like)

### Markdown Formatting Standards

```markdown
# Main Title

## Section Headers (##)

### Subsections (###)

#### Details (####)

**Bold for emphasis**
*Italic for terms*
`code for commands/files`

Tables for structured data:
| Column 1 | Column 2 |
|----------|----------|
| Value    | Value    |

Code blocks with language:
```python
code here
```

Lists:
- Bullet points
1. Numbered lists
```

---

## Using Templates Effectively

### Step 1: Copy Template
```bash
cp docs/templates/[template-name].md docs/[destination]/[new-name].md
```

### Step 2: Replace Placeholders
- Search for `[` to find all placeholders
- Replace with actual values
- Remove example content if not needed

### Step 3: Verify Content
- Check against actual code
- Run queries to verify examples
- Test any commands provided
- Mark as verified at top of doc

### Step 4: Link & Index
- Add to appropriate README
- Update navigation docs
- Cross-reference from related docs

---

## Template Maintenance

### When to Update Templates

Update templates when:
- 🔄 **New pattern emerges** - 3+ processors use same structure
- 📊 **Better practices identified** - New best practice worth standardizing
- 🐛 **Common mistakes found** - Add guidance to prevent repeated issues
- 📝 **Feedback received** - Users suggest improvements

### Version Control

Each template should have:
```markdown
**Last Updated**: [Date]
**Version**: X.Y
**Changelog**:
- vX.Y: [What changed]
- vX.Y-1: [Previous change]
```

### Quality Checks

Before adding a new template:
- [ ] Used in at least 2 real documents
- [ ] All sections have examples
- [ ] Placeholders clearly marked `[like this]`
- [ ] This README updated with usage instructions
- [ ] Reviewed by at least one other person

---

## Planned Templates

Future templates to add:

### High Priority
- **Implementation Plan Template** - For feature planning docs
- **API Documentation Template** - For API endpoints/services
- **Architecture Decision Record (ADR)** - For design decisions

### Medium Priority
- **Troubleshooting Guide Template** - For operational guides
- **Deployment Checklist Template** - For deployment procedures
- **Performance Analysis Template** - For performance investigations

### Low Priority
- **Meeting Notes Template** - For design discussions
- **Incident Post-Mortem Template** - For incident analysis
- **Testing Strategy Template** - For test plans

---

## Related Documentation

### Using Processor Cards
- [Processor Cards Index](../processor-cards/README.md) - All completed processor cards
- [Processor Documentation Guide](../guides/05-processor-documentation-guide.md) - How to document processors

### Documentation Standards
- [Documentation Guide](../DOCUMENTATION_GUIDE.md) - Overall documentation standards
- [Navigation Guide](../NAVIGATION_GUIDE.md) - How docs are organized

### Examples
- [Examples Directory](../examples/) - Code examples using these patterns

---

## Contributing

### Adding a New Template

1. **Identify the need** - Used in 2+ documents
2. **Create template** with clear placeholders
3. **Add examples** showing expected content
4. **Document usage** in this README
5. **Get review** from another team member
6. **Use it** in real documentation

### Improving Existing Templates

1. **Note the issue** - What's missing or unclear?
2. **Propose change** - How to improve it?
3. **Update template** and this README
4. **Update version** and changelog in template
5. **Consider** updating existing docs using the template

---

## Template Quality Metrics

| Template | Usage Count | Last Updated | Quality |
|----------|-------------|--------------|---------|
| processor-reference-card | 13 docs | 2025-11-15 | ⭐⭐⭐⭐⭐ |

**Usage count:** How many docs currently use this template
**Quality rating:** Based on clarity, completeness, usefulness

---

**Directory Status:** ✅ Active
**Templates Count:** 1 (processor reference card)
**Documents Using Templates:** 13 processor cards
**Planned Additions:** 3 high priority, 3 medium priority templates
