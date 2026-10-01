def request_approval(tool_name: str, params: dict, reason: str) -> bool:
    """
    审批门。高风险操作暂停等用户确认。
    先用命令行模拟，以后换成 Flutter UI。
    """
    print(f"\n[审批请求] 工具: {tool_name}")
    print(f"  参数: {params}")
    print(f"  原因: {reason}")
    ans = input("  是否允许? (y/N): ").strip().lower()
    return ans == "y"


if __name__ == "__main__":
    ok = request_approval("run_shell", {"command": "rm -rf /"}, "高风险操作")
    print("审批结果:", ok)