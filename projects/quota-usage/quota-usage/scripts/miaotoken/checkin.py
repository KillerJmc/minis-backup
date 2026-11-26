#!/usr/bin/env python3
"""妙词元没有签到功能（站点 /api/status 的 checkin_enabled 为 false）。

保留此文件是为了让 route.py 的统一入口有实现可调；调用时给出明确说明，
不伪造成功。

退出码：0 表示「查询完成，结论是该平台无此功能」。
"""
import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description="妙词元签到（不支持）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-exchange", action="store_true")
    args = ap.parse_args()

    msg = "妙词元没有签到功能（checkin_enabled = false）"
    if args.json:
        print(json.dumps({"platform": "miaotoken", "supported": False,
                          "message": msg}, ensure_ascii=False))
    else:
        print(f"ℹ️  {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())