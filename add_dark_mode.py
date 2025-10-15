"""
Dark Mode Template Updater
Automatically adds dark mode Tailwind classes to Django templates.

Usage:
    python add_dark_mode.py           # Update all templates
    python add_dark_mode.py --dry-run # Preview changes without writing
    python add_dark_mode.py --verbose # Show detailed output
"""

import os
import re
import argparse
from pathlib import Path

# Mapping of light mode classes to dark mode variants
DARK_MODE_CLASSES = {
    'bg-white': 'bg-white dark:bg-gray-800',
    'bg-gray-50': 'bg-gray-50 dark:bg-gray-900',
    'bg-gray-100': 'bg-gray-100 dark:bg-gray-800',
    'text-gray-900': 'text-gray-900 dark:text-gray-100',
    'text-gray-800': 'text-gray-800 dark:text-gray-200',
    'text-gray-700': 'text-gray-700 dark:text-gray-300',
    'text-gray-600': 'text-gray-600 dark:text-gray-400',
    'text-gray-500': 'text-gray-500 dark:text-gray-400',
    'border-gray-200': 'border-gray-200 dark:border-gray-700',
    'border-gray-300': 'border-gray-300 dark:border-gray-600',
    'divide-gray-200': 'divide-gray-200 dark:divide-gray-700',
    'hover:bg-gray-50': 'hover:bg-gray-50 dark:hover:bg-gray-700',
    'hover:bg-gray-100': 'hover:bg-gray-100 dark:hover:bg-gray-700',
    'hover:text-gray-900': 'hover:text-gray-900 dark:hover:text-gray-100',
    'ring-gray-300': 'ring-gray-300 dark:ring-gray-600',
}

# Files and directories to exclude
EXCLUDE_FILES = {
    'base_public.html',  # Public pages remain light only
}

EXCLUDE_DIRS = {
    'patient_portal',    # Patient portal remains light only
    'emails',            # Email templates stay light
}

# PDF template patterns to exclude
PDF_PATTERNS = [
    '_pdf.html',
    '_pdf_',
    'pdf.html',
]


def should_exclude_file(file_path):
    """Check if file should be excluded from processing."""
    file_name = os.path.basename(file_path)
    
    # Check exact filename matches
    if file_name in EXCLUDE_FILES:
        return True
    
    # Check if it's a PDF template
    for pattern in PDF_PATTERNS:
        if pattern in file_name.lower():
            return True
    
    return False


def should_exclude_dir(dir_name):
    """Check if directory should be excluded from processing."""
    return dir_name in EXCLUDE_DIRS


def already_has_dark_mode(content, class_name):
    """Check if a class already has dark mode variant nearby."""
    # Find all occurrences of the class
    pattern = rf'\b{re.escape(class_name)}\b'
    matches = re.finditer(pattern, content)
    
    for match in matches:
        # Check if 'dark:' appears in the same class attribute
        start = match.start()
        # Look backwards and forwards for class=" boundaries
        class_start = content.rfind('class="', 0, start)
        class_end = content.find('"', start)
        
        if class_start != -1 and class_end != -1:
            class_content = content[class_start:class_end]
            if 'dark:' in class_content:
                return True
    
    return False


def update_template(file_path, dry_run=False, verbose=False):
    """Update a single template file with dark mode classes."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"  ❌ Error reading {file_path}: {e}")
        return False
    
    original_content = content
    changes_made = []
    
    # Update classes
    for light_class, dark_class in DARK_MODE_CLASSES.items():
        if light_class in content:
            # Only replace if dark variant doesn't already exist
            if not already_has_dark_mode(content, light_class):
                occurrences = content.count(light_class)
                content = content.replace(light_class, dark_class)
                if verbose:
                    changes_made.append(f"{light_class} ({occurrences}x)")
    
    # Check if changes were made
    if content != original_content:
        if not dry_run:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"  ✅ Updated: {file_path}")
            except Exception as e:
                print(f"  ❌ Error writing {file_path}: {e}")
                return False
        else:
            print(f"  🔍 Would update: {file_path}")
        
        if verbose and changes_made:
            for change in changes_made:
                print(f"      - {change}")
        
        return True
    else:
        if verbose:
            print(f"  ⏭️  Skipped (no changes needed): {file_path}")
        return False


def find_templates(base_dir='templates'):
    """Find all HTML template files that should be processed."""
    templates = []
    excluded_count = 0
    
    for root, dirs, files in os.walk(base_dir):
        # Get the directory name
        current_dir = os.path.basename(root)
        
        # Remove excluded directories from traversal
        dirs[:] = [d for d in dirs if not should_exclude_dir(d)]
        
        for file in files:
            if file.endswith('.html'):
                file_path = os.path.join(root, file)
                
                if should_exclude_file(file_path):
                    excluded_count += 1
                    continue
                
                templates.append(file_path)
    
    return templates, excluded_count


def main():
    """Main function to update all templates."""
    parser = argparse.ArgumentParser(
        description='Add dark mode classes to Django templates'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying files'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show detailed output for each file'
    )
    parser.add_argument(
        '--templates-dir',
        default='templates',
        help='Path to templates directory (default: templates)'
    )
    
    args = parser.parse_args()
    
    print("🎨 Dark Mode Template Updater")
    print("=" * 60)
    
    if args.dry_run:
        print("🔍 DRY RUN MODE - No files will be modified")
        print("=" * 60)
    
    # Check if templates directory exists
    if not os.path.exists(args.templates_dir):
        print(f"\n❌ Error: Templates directory not found: {args.templates_dir}")
        print("   Make sure you're running this from your project root.")
        return
    
    print(f"\n📁 Scanning templates directory: {args.templates_dir}")
    templates, excluded_count = find_templates(args.templates_dir)
    
    print(f"\n📊 Summary:")
    print(f"   - Found: {len(templates)} templates to process")
    print(f"   - Excluded: {excluded_count} templates (public/email/PDF)")
    
    if excluded_count > 0:
        print(f"\n📋 Excluded directories: {', '.join(EXCLUDE_DIRS)}")
        print(f"   Excluded files: {', '.join(EXCLUDE_FILES)}")
        print(f"   Excluded patterns: {', '.join(PDF_PATTERNS)}")
    
    if not templates:
        print("\n⚠️  No templates found to process!")
        return
    
    print(f"\n🔄 Processing templates...\n")
    
    updated_count = 0
    for template in sorted(templates):
        # Show relative path for cleaner output
        rel_path = os.path.relpath(template, args.templates_dir)
        print(f"Processing: templates/{rel_path}")
        
        if update_template(template, dry_run=args.dry_run, verbose=args.verbose):
            updated_count += 1
    
    print("\n" + "=" * 60)
    
    if args.dry_run:
        print(f"\n🔍 Dry run complete!")
        print(f"   {updated_count} out of {len(templates)} templates would be updated")
        print(f"\n   Run without --dry-run to apply changes")
    else:
        print(f"\n✨ Complete! Updated {updated_count} out of {len(templates)} templates")
        
        if updated_count > 0:
            print(f"\n⚠️  IMPORTANT: Review the changes before committing!")
            print(f"   Run: git diff {args.templates_dir}/")
            print(f"\n   If happy with changes:")
            print(f"   git add {args.templates_dir}/")
            print(f"   git commit -m 'Add dark mode support to templates'")
        else:
            print(f"\n✅ All templates are already up to date!")


if __name__ == '__main__':
    main()