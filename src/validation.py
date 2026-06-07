"""
validation.py
==============
项目回归测试入口 (Regression Test Harness).

用例：
  --case m1   Patched conic 验证
  --case m2   N 体 Velocity-Verlet 积分器验证
  --case m3   JPL Horizons 历表对照
  --case m4   月球借力解析模型验证
  --case m5   单点轨道求解器验证
  --case m6   发射窗口优化验证
  --case m7   灵敏度分析验证
  --case m8   可视化结果验证
  --case all  全部回归测试
  make validate  全部回归测试
"""

import sys
import argparse


def _run_case(case_name: str) -> bool:
    """运行指定的回归测试用例。"""
    if case_name == "m1":
        from patched_conic import _run_m1_regression
        _run_m1_regression()
        return True
    elif case_name == "m2":
        from nbody import _run_m2_regression
        _run_m2_regression()
        return True
    elif case_name == "m3":
        from horizons import _run_m3_regression
        _run_m3_regression()
        return True
    elif case_name == "m4":
        from lunar_swingby import _run_m4_regression
        _run_m4_regression()
        return True
    elif case_name == "m5":
        from trajectory import _run_m5_regression
        _run_m5_regression()
        return True
    elif case_name == "m6":
        from optimize_window import _run_m6_regression
        _run_m6_regression()
        return True
    elif case_name == "m7":
        from sensitivity import _run_m7_regression
        _run_m7_regression()
        return True
    elif case_name == "m8":
        from plotting import _run_m8_regression
        _run_m8_regression()
        return True
    else:
        print(f"Unknown case: {case_name}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="MSPJ Final Project - Regression Test Harness"
    )
    parser.add_argument(
        "--case", "-c",
        default="all",
        help="Test case: m1, m2, m3, m4, m5, or all (default: all)",
    )
    args = parser.parse_args()

    cases = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]
    if args.case != "all":
        cases = [args.case]

    all_passed = True
    for case in cases:
        print(f"\n{'#' * 66}")
        print(f"# Running {case.upper()} regression...")
        print(f"{'#' * 66}")
        try:
            _run_case(case)
        except Exception as e:
            print(f"\n{'!' * 66}")
            print(f"!!! {case.upper()} regression FAILED: {e}")
            print(f"{'!' * 66}")
            all_passed = False

    print(f"\n{'=' * 66}")
    if all_passed:
        print("All regression scripts executed without exception [OK]")
        print("NOTE: \"PASSED\" means script ran successfully, NOT that the")
        print("specification threshold was met. See FINAL_AUDIT.md for per-milestone")
        print("specification compliance status (done / partial / missing).")
    else:
        print("SOME regression tests FAILED")
    print(f"{'=' * 66}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
