#!/usr/bin/env python3
"""
Sentinel AI Test Runner
Organizes and runs all test suites with proper reporting
"""
import os
import sys
import subprocess
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

def run_test_category(category_name, test_path):
    """Run tests in a specific category"""
    print(f"\n🧪 Running {category_name} Tests...")
    print("=" * 60)
    
    if not os.path.exists(test_path):
        print(f"❌ Test directory not found: {test_path}")
        return False
    
    test_files = list(Path(test_path).glob("test_*.py"))
    if not test_files:
        print(f"⚠️  No test files found in {test_path}")
        return True
    
    # Use the venv Python executable
    python_exe = str(project_root / ".venv" / "bin" / "python")
    if not os.path.exists(python_exe):
        python_exe = sys.executable  # Fallback to current Python
    
    success_count = 0
    total_count = len(test_files)
    
    for test_file in test_files:
        print(f"\n▶️  Running {test_file.name}...")
        start_time = time.time()
        
        try:
            # Change to project root for relative imports
            result = subprocess.run(
                [python_exe, str(test_file)],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=120  # 2 minute timeout per test
            )
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                print(f"✅ PASSED in {duration:.1f}s")
                success_count += 1
            else:
                print(f"❌ FAILED in {duration:.1f}s")
                if result.stderr:
                    print(f"   Error: {result.stderr[:200]}...")
                if result.stdout:
                    print(f"   Output: {result.stdout[:200]}...")
        except subprocess.TimeoutExpired:
            print(f"⏰ TIMEOUT after 120s")
        except Exception as e:
            print(f"💥 ERROR: {e}")
    
    print(f"\n📊 {category_name} Summary: {success_count}/{total_count} tests passed")
    return success_count == total_count

def main():
    """Run all organized test suites"""
    print("🧪 Sentinel AI Organized Test Suite")
    print("Testing LLM Provider Priority: Grok → OpenAI → Moonshot → DeepSeek")
    print("=" * 80)
    
    start_time = time.time()
    
    # Define test categories
    test_categories = [
        ("Advisor", "tests/advisor"),
        ("LLM Routing", "tests/llm"),
        ("Geographic", "tests/geographic"),
        ("Performance", "tests/performance"),
    ]
    
    results = {}
    
    for category_name, test_path in test_categories:
        results[category_name] = run_test_category(category_name, test_path)
    
    # Summary
    total_duration = time.time() - start_time
    print("\n" + "=" * 80)
    print("📋 Final Test Summary")
    print("=" * 80)
    
    all_passed = True
    for category, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"   {status} {category}")
        if not passed:
            all_passed = False
    
    print(f"\n⏱️  Total Duration: {total_duration:.1f}s")
    
    if all_passed:
        print("🎉 All test categories completed successfully!")
        print("💡 LLM provider priority is working as expected.")
    else:
        print("⚠️  Some tests failed. Check individual results above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
