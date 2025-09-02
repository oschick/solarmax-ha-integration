# HACS Setup Guide

This document explains how to prepare your Solarmax integration repository for HACS compatibility.

## Required Files Created

### Core HACS Files
- ✅ `hacs.json` - HACS configuration file
- ✅ `info.md` - Short description for HACS store
- ✅ `README.md` - Comprehensive documentation
- ✅ `LICENSE` - MIT license file

### GitHub Repository Files
- ✅ `.gitignore` - Git ignore patterns
- ✅ `CHANGELOG.md` - Version history
- ✅ `CONTRIBUTING.md` - Contribution guidelines
- ✅ `.github/workflows/validate.yml` - HACS validation workflow
- ✅ `.github/workflows/release.yml` - Release automation
- ✅ `.github/ISSUE_TEMPLATE/` - Issue templates
- ✅ `.github/pull_request_template.md` - PR template

### Development Files
- ✅ `requirements_dev.txt` - Development dependencies
- ✅ `.pre-commit-config.yaml` - Pre-commit hooks
- ✅ `pyproject.toml` - Python project configuration
- ✅ `tests/` - Basic test structure

### Integration Files (Updated)
- ✅ `custom_components/solarmax/manifest.json` - Added integration_type

## Next Steps to Complete HACS Setup

### 1. GitHub Repository Setup
```bash
# Initialize git repository (if not already done)
git init
git add .
git commit -m "Initial commit - HACS compatible"

# Add remote repository
git remote add origin https://github.com/oschick/solarmax-ha-integration.git
git push -u origin main
```

### 2. Create Initial Release
1. Go to your GitHub repository
2. Click "Releases" → "Create a new release"
3. Tag version: `v1.0.0`
4. Release title: `Initial Release v1.0.0`
5. Add description from CHANGELOG.md
6. Publish release

### 3. HACS Installation Options

#### Option A: Add to HACS as Custom Repository
Users can add your repository manually:
1. HACS → Integrations → ⋮ → Custom repositories
2. Add repository URL: `https://github.com/oschick/solarmax-ha-integration`
3. Category: Integration

#### Option B: Submit to HACS Default Store
1. Fork the HACS default repository
2. Add your repository to the integration list
3. Create a pull request
4. Wait for review and approval

### 4. Validation
The GitHub Actions workflows will automatically:
- Validate HACS compatibility
- Run hassfest validation
- Create release assets

## Repository Structure
```
solarmax-agent/
├── custom_components/solarmax/    # Integration code
├── .github/                       # GitHub workflows and templates
├── tests/                         # Test files
├── README.md                      # Main documentation
├── LICENSE                        # License file
├── hacs.json                      # HACS configuration
├── info.md                        # HACS store description
├── CHANGELOG.md                   # Version history
├── CONTRIBUTING.md                # Contribution guide
└── pyproject.toml                 # Python configuration
```

## HACS Requirements Checklist
- ✅ Repository is public
- ✅ Has a clear README.md
- ✅ Has proper LICENSE file
- ✅ Has hacs.json configuration
- ✅ Integration has manifest.json
- ✅ Follows Home Assistant development guidelines
- ✅ Has GitHub releases
- ✅ Has proper version numbering (semver)

## Testing HACS Compatibility
```bash
# Install HACS validation tool
pip install homeassistant

# Run validation
hacs validate --repository . --category integration
```

## Common HACS Issues and Solutions

### Issue: "Repository structure is not correct"
- Ensure `custom_components/solarmax/` structure is correct
- Check manifest.json is valid

### Issue: "No releases found"
- Create at least one GitHub release
- Use semantic versioning (v1.0.0, v1.0.1, etc.)

### Issue: "Invalid hacs.json"
- Validate JSON syntax
- Ensure all required fields are present

## Maintenance
- Update version in manifest.json for each release
- Update CHANGELOG.md with new features/fixes
- Create GitHub releases for version updates
- Monitor GitHub Actions for validation failures

Your repository is now fully HACS compatible! 🎉
