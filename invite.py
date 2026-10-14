#!/usr/bin/env python3
"""
邀请码管理 & 下载服务器

管理邀请码，限制每个码最多3次下载。

用法:
  python invite.py generate [数量]          # 生成邀请码
  python invite.py list                     # 列出所有邀请码及使用情况
  python invite.py serve [端口]              # 启动下载服务器
  python invite.py check <邀请码>            # 检查邀请码状态
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# 数据文件
CODES_FILE = Path(__file__).resolve().parent / "invite_codes.json"
# EXE 路径
EXE_PATH = Path(__file__).resolve().parent / "dist" / "PPT转视频工具.exe"

# 每个邀请码最大下载次数
MAX_DOWNLOADS_PER_CODE = 3


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


def _load_codes() -> dict:
    """加载邀请码数据库。"""
    if CODES_FILE.exists():
        try:
            data = json.loads(CODES_FILE.read_text(encoding="utf-8"))
            # 确保结构完整
            if "codes" not in data:
                data["codes"] = {}
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"codes": {}, "created_at": datetime.now(timezone.utc).isoformat()}


def _save_codes(data: dict) -> None:
    """保存邀请码数据库。"""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    CODES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    try:
        CODES_FILE.chmod(0o600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 命令: 生成邀请码
# ---------------------------------------------------------------------------


def cmd_generate(count: int = 1) -> None:
    """生成指定数量的邀请码。"""
    data = _load_codes()

    new_codes = []
    for _ in range(count):
        # 8位字母数字组合，带校验位
        raw = secrets.token_hex(4).upper()[:8]
        code = "-".join([raw[:4], raw[4:]])

        data["codes"][code] = {
            "created": datetime.now(timezone.utc).isoformat(),
            "downloads": 0,
            "max_downloads": MAX_DOWNLOADS_PER_CODE,
            "active": True,
        }
        new_codes.append(code)

    _save_codes(data)

    print(f"\n✅ 生成了 {count} 个邀请码：\n")
    for code in new_codes:
        print(f"   {code}")
    print(f"\n每个邀请码最多可下载 {MAX_DOWNLOADS_PER_CODE} 次")
    print(f"数据已保存到: {CODES_FILE}\n")


# ---------------------------------------------------------------------------
# 命令: 列出邀请码
# ---------------------------------------------------------------------------


def cmd_list() -> None:
    """列出所有邀请码及使用情况。"""
    data = _load_codes()
    codes = data.get("codes", {})

    if not codes:
        print("\n📭 暂无邀请码，请先运行: python invite.py generate\n")
        return

    print(f"\n{'=' * 60}")
    print(f"  邀请码状态总览 ({len(codes)} 个)")
    print(f"{'=' * 60}")
    print(f"  {'邀请码':<20} {'已下载':<10} {'剩余':<8} {'状态':<8}")
    print(f"  {'-' * 46}")

    active = 0
    total_downloads = 0
    for code, info in sorted(codes.items()):
        dls = info.get("downloads", 0)
        max_dl = info.get("max_downloads", MAX_DOWNLOADS_PER_CODE)
        remaining = max(0, max_dl - dls)
        status = info.get("active", True)
        status_str = "✅ 有效" if status else "❌ 停用"
        if remaining <= 0:
            status_str = "🔴 已满"
        print(f"  {code:<20} {dls:<10} {remaining:<8} {status_str:<8}")
        if status and remaining > 0:
            active += 1
        total_downloads += dls

    print(f"  {'-' * 46}")
    print(f"  总下载次数: {total_downloads}")
    print(f"  有效邀请码: {active}")
    print()


# ---------------------------------------------------------------------------
# 命令: 检查邀请码
# ---------------------------------------------------------------------------


def cmd_check(code: str) -> None:
    """检查单个邀请码的状态。"""
    data = _load_codes()
    codes = data.get("codes", {})
    info = codes.get(code)

    if not info:
        print(f"\n❌ 邀请码 {code} 不存在\n")
        return

    dls = info.get("downloads", 0)
    max_dl = info.get("max_downloads", MAX_DOWNLOADS_PER_CODE)
    remaining = max(0, max_dl - dls)
    status = info.get("active", True)
    created = info.get("created", "unknown")

    print(f"\n{'=' * 50}")
    print(f"  邀请码: {code}")
    print(f"{'=' * 50}")
    print(f"  状态:     {'✅ 有效' if status and remaining > 0 else '🔴 已失效'}")
    print(f"  创建时间: {created}")
    print(f"  已下载:   {dls} 次")
    print(f"  剩余:     {remaining} 次")
    print(f"  上限:     {max_dl} 次")
    print()


# ---------------------------------------------------------------------------
# 下载服务器
# ---------------------------------------------------------------------------


def _validate_code(code: str, data: dict) -> Optional[str]:
    """验证邀请码，返回错误信息或 None（有效）。"""
    codes = data.get("codes", {})
    info = codes.get(code)
    if not info:
        return f"邀请码 {code} 不存在"
    if not info.get("active", True):
        return "该邀请码已被停用"
    dls = info.get("downloads", 0)
    max_dl = info.get("max_downloads", MAX_DOWNLOADS_PER_CODE)
    if dls >= max_dl:
        return f"该邀请码已达到下载上限 ({max_dl} 次)"
    return None


def cmd_serve(port: int = 8080) -> None:
    """启动 HTTP 下载服务器。"""
    if not EXE_PATH.exists():
        print(f"\n❌ EXE 文件不存在: {EXE_PATH}")
        print(f"请先运行 build.bat 打包 EXE\n")
        sys.exit(1)

    exe_size_mb = EXE_PATH.stat().st_size / 1e6
    print(f"\n{'=' * 50}")
    print(f"  PPT转视频工具 — 下载服务器")
    print(f"{'=' * 50}")
    print(f"  EXE: {EXE_PATH.name} ({exe_size_mb:.0f} MB)")
    print(f"  端口: {port}")
    print(f"  限制: 每个邀请码最多 {MAX_DOWNLOADS_PER_CODE} 次下载")
    print()
    print(f"  用户下载地址:")
    print(f"  http://localhost:{port}/download?code=XXX")
    print(f"  http://<你的IP>:{port}/download?code=XXX")
    print()
    print(f"  管理地址:")
    print(f"  http://localhost:{port}/status")
    print(f"  http://localhost:{port}/check?code=XXX")
    print()
    print(f"  按 Ctrl+C 停止服务器")
    print(f"{'=' * 50}\n")

    import http.server

    class InviteHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            logger.info("%s - %s", self.client_address[0], format % args)

        def _send_json(self, data: dict, status: int = 200):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str, status: int = 200):
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_exe(self, code: str):
            """验证邀请码并下发 EXE。"""
            data = _load_codes()
            err = _validate_code(code, data)
            if err:
                self._send_html(f"""
                <html><body style="font-family:sans-serif;padding:40px;background:#0f0e1a;color:#e8e8f0">
                <h2 style="color:#f87171">❌ 下载失败</h2>
                <p>{err}</p>
                <p><a href="/" style="color:#7c5cfc">返回首页</a></p>
                </body></html>""", 403)
                return

            # 更新下载计数
            data["codes"][code]["downloads"] += 1
            data["codes"][code]["last_download"] = datetime.now(timezone.utc).isoformat()
            _save_codes(data)

            # 下发文件
            exe_bytes = EXE_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition",
                             f'attachment; filename="{EXE_PATH.name}"')
            self.send_header("Content-Length", str(len(exe_bytes)))
            self.end_headers()
            self.wfile.write(exe_bytes)

            logger.info(
                "✅ 已下发: code=%s, downloads=%d/%d",
                code,
                data["codes"][code]["downloads"],
                data["codes"][code]["max_downloads"],
            )

        def do_GET(self):
            path = self.path
            # 首页
            if path == "/" or path == "/index.html":
                self._send_html(f"""
                <html><body style="font-family:sans-serif;padding:40px;background:#0f0e1a;color:#e8e8f0;max-width:600px;margin:auto">
                <h1 style="color:#7c5cfc">📽️ PPT转视频工具</h1>
                <p>请输入邀请码下载工具</p>
                <form action="/download" method="get" style="margin:20px 0">
                <input type="text" name="code" placeholder="输入邀请码 (如: ABCD-1234)"
                       style="width:100%;padding:12px;font-size:16px;background:#1a1a2e;color:#e8e8f0;
                              border:1px solid #2d2b55;border-radius:6px;box-sizing:border-box">
                <br><br>
                <button type="submit"
                        style="background:#7c5cfc;color:white;border:none;padding:12px 30px;
                               font-size:16px;border-radius:6px;cursor:pointer">
                ⬇️ 下载 EXE
                </button>
                </form>
                <p style="color:#888;font-size:14px">每个邀请码最多可下载 {MAX_DOWNLOADS_PER_CODE} 次</p>
                </body></html>""")
                return

            # 下载
            if path.startswith("/download"):
                from urllib.parse import urlparse, parse_qs
                params = parse_qs(urlparse(path).query)
                code = params.get("code", [""])[0].strip().upper()
                if not code:
                    self._send_html("<h2>❌ 请提供邀请码</h2><p>用法: /download?code=XXXX-XXXX</p>", 400)
                    return
                self._serve_exe(code)
                return

            # 检查邀请码状态
            if path.startswith("/check"):
                from urllib.parse import urlparse, parse_qs
                params = parse_qs(urlparse(path).query)
                code = params.get("code", [""])[0].strip().upper()
                if not code:
                    self._send_json({"error": "请提供邀请码"}, 400)
                    return
                data = _load_codes()
                err = _validate_code(code, data)
                info = data.get("codes", {}).get(code, {})
                self._send_json({
                    "code": code,
                    "valid": err is None,
                    "error": err,
                    "downloads": info.get("downloads", 0),
                    "remaining": max(0, info.get("max_downloads", MAX_DOWNLOADS_PER_CODE) - info.get("downloads", 0)),
                    "max_downloads": info.get("max_downloads", MAX_DOWNLOADS_PER_CODE),
                })
                return

            # 状态页
            if path == "/status":
                data = _load_codes()
                codes = data.get("codes", {})
                total = len(codes)
                active = sum(1 for c in codes.values()
                             if c.get("active", True) and
                             c.get("downloads", 0) < c.get("max_downloads", MAX_DOWNLOADS_PER_CODE))
                total_dls = sum(c.get("downloads", 0) for c in codes.values())
                self._send_json({
                    "total_codes": total,
                    "active_codes": active,
                    "total_downloads": total_dls,
                    "max_per_code": MAX_DOWNLOADS_PER_CODE,
                    "exe_size_mb": round(exe_size_mb, 1),
                    "codes": {
                        k: {
                            "downloads": v.get("downloads", 0),
                            "remaining": max(0, v.get("max_downloads", MAX_DOWNLOADS_PER_CODE) - v.get("downloads", 0)),
                            "active": v.get("active", True),
                        }
                        for k, v in sorted(codes.items())
                    },
                })
                return

            # 404
            self._send_html("<h2>404 Not Found</h2>", 404)

    # 启动服务器
    server = http.server.HTTPServer(("0.0.0.0", port), InviteHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n服务器已停止\n")
        server.server_close()


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PPT转视频工具 — 邀请码管理 & 下载服务器",
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    # generate
    gen = sub.add_parser("generate", help="生成邀请码")
    gen.add_argument("count", type=int, default=1, nargs="?",
                     help="生成数量（默认: 1）")

    # list
    sub.add_parser("list", help="列出所有邀请码")

    # check
    chk = sub.add_parser("check", help="检查邀请码状态")
    chk.add_argument("code", type=str, help="邀请码")

    # serve
    sv = sub.add_parser("serve", help="启动下载服务器")
    sv.add_argument("port", type=int, default=8080, nargs="?",
                    help="端口号（默认: 8080）")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args.count)
    elif args.command == "list":
        cmd_list()
    elif args.command == "check":
        cmd_check(args.code.upper())
    elif args.command == "serve":
        cmd_serve(args.port)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
