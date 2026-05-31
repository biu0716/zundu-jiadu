"""命令行入口。
用法：
  python main.py "隔夜水到底能不能喝？"     # 单条核查
  python main.py                            # 进入交互模式，逐条输入
  python main.py --demo                     # 跑 5 条内置金牌案例（含一对镜像）
"""
import sys
import json
from verifier import FactVerifier

VERDICT_ICON = {"谣言": "❌", "误导性": "⚠️", "部分属实": "◐", "属实": "✅", "缺乏证据": "❓"}

DEMO_CASES = [
    "经常喝隔夜水会致癌，赶紧告诉家里人别喝了",
    "高血压血压降下来就可以停药了，不用一直吃降压药",
    "头孢配酒根本死不了，顶多胃有点不舒服",      # 镜像A：把危险说成安全
    "维生素C和虾一起吃会生成砒霜，等于服毒",      # 镜像B：把安全说成危险
    "想看钱塘江不给钱围起来都不给你看",
]


def render(result):
    """把核查结果按"调查记者破案"的方式逐步打印——即 demo 里的四步显形。"""
    icon = VERDICT_ICON.get(result["verdict"], "")
    print("\n" + "=" * 56)
    print(f"📨 待核查：{result['input']}")
    print("-" * 56)
    for i, step in enumerate(["溯源", "交叉验证", "逻辑推演", "证据链"], 1):
        print(f"  [{i}] {step}：{result['trace'].get(step, '')}")
    print("-" * 56)
    print(f"{icon} 判定：{result['verdict']}　|　置信度 {result['confidence']}　|　来源路径：{result['source_path']}")
    if result["high_risk"] and result.get("safety_note"):
        print("🚨 高危条：卡片须显著标注安全提示")
        print(f"   ⚠️ {result['safety_note']}")
    print(f"\n🟢 真相：{result['truth']}")
    if result.get("analogy"):
        print(f"🔢 生活化比喻：{result['analogy']['text']}")
        print(f"   （出处：{result['analogy']['source']}）")
    if result["tactics"]:
        print(f"🎭 话术拆解：{ ' / '.join(result['tactics']) }")
    if result["sources"]:
        print("🏛️ 权威来源：")
        for s in result["sources"]:
            print(f"   - {s}")
    print("=" * 56)


def main():
    args = sys.argv[1:]
    verifier = FactVerifier()
    print(f"[启动] 知识库后端：{verifier.kb.backend_name}　| 大模型：{'已配置' if verifier.llm.available else '未配置（走离线/知识库路径）'}")

    if args and args[0] == "--demo":
        for case in DEMO_CASES:
            render(verifier.verify(case))
        return
    if args:
        render(verifier.verify(" ".join(args)))
        return

    print("进入交互模式，粘贴一条可疑信息后回车（输入 q 退出）：")
    while True:
        try:
            text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("q", "quit", "exit"):
            break
        if text:
            render(verifier.verify(text))


if __name__ == "__main__":
    main()
