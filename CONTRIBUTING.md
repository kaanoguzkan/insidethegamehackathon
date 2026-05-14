# Contributing to Agents League

Thank you for your interest! This is a competition repository, so contributions are limited to improvements that help all participants.

## ✅ What We Welcome

- **Bug reports** for starter kits or documentation
- **Documentation fixes** (typos, clarifications, broken links)
- **Starter kit improvements** (bug fixes, better examples)
- **Community resources** (helpful guides, tools)

## ❌ What We Don't Accept

- Changes to evaluation criteria or rules during competition
- Direct edits to competition submissions

## 🐛 Reporting Issues

Found a bug? [Open an issue](https://github.com/microsoft/agentsleague/issues/new) with:
- Clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Your environment (OS, versions)

## 📝 How to Contribute

### Documentation or Starter Kit Fixes

1. Fork this repository
2. Make your changes
3. Test that everything works
4. Submit a Pull Request with:
   - **Title**: `Fix: [brief description]` or `Docs: [what you improved]`
   - **Description**: What you changed and why

### Adding Community Resources

Have a helpful guide or tool? Share it in [Discord](https://aka.ms/agentsleague/discord) or open an issue to suggest adding it to the README.

## 📋 Pull Request Guidelines

**Good PR titles:**
- `Fix: Broken link in reasoning-agents README`
- `Docs: Clarify Azure setup steps`
- `Fix: Starter kit dependency error`

**In your PR description:**
- What you changed
- Why it's helpful
- How you tested it

## Type of Change
- [ ] Bug fix
- [ ] Documentation improvement
- [ ] New example or resource
- [ ] Starter kit enhancement

## Testing
How have you tested these changes?

## Checklist
- [ ] Code follows the existing style
- [ ] Documentation is updated
- [ ] All links work
- [ ] No secrets in code
- [ ] Changes are backwards compatible (if applicable)
```

### Review Process

1. **Automated checks**: Linting, link validation
2. **Maintainer review**: Program team reviews your PR
3. **Feedback**: Address any requested changes
4. **Merge**: Once approved, we'll merge your contribution!

**Timeline**: We aim to review PRs within 2-3 business days during the competition.

## 🐛 Reporting Security Issues

**Do NOT** open public issues for security vulnerabilities.

Instead:
- Email: <aycabas@microsoft.com> with `[SECURITY]` in subject
- Describe the vulnerability
- Steps to reproduce
- Potential impact

We'll respond within 48 hours and work with you to resolve the issue.

## 💬 Community Support

### Helping Others

The best contribution? Helping fellow participants!

**On Discord**:
- Answer questions in track channels
- Share tips and resources
- Provide encouragement
- Debug together (without doing the work for them)

**On GitHub**:
- Comment on issues with helpful suggestions
- Review others' questions (not submissions)
- Share your own experiences

## 🎓 Best Practices

### Code Style

**Python**:
```python
# Use type hints
def process_input(query: str) -> dict:
    """Process user query and return results."""
    pass

# Follow PEP 8
# Use descriptive names
# Add docstrings for functions
```

**TypeScript/JavaScript**:
```typescript
// Use TypeScript when possible
interface AgentResponse {
    result: string;
    confidence: number;
}

// Clear function signatures
async function processQuery(query: string): Promise<AgentResponse> {
    // Implementation
}

// Use async/await over .then()
// Add JSDoc comments
```

## ⚖️ License & Code of Conduct

- All contributions are licensed under the MIT License
- Follow our [Code of Conduct](./CODE_OF_CONDUCT.md) - be respectful and inclusive

## 📧 Questions?

- Ask on [Discord](https://aka.ms/agentsleague/discord) in #general
- Email: <aycabas@microsoft.com>
- Open an issue for discussion

---

Thank you for helping make Agents League better! 🎉
