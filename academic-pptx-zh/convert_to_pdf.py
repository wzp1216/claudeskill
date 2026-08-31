#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 python 驱动 WPS Office 将 .pptx/.potx 转为 PDF（替代 LibreOffice）。

用法:
    python convert_to_pdf.py <输入.pptx> <输出.pdf>

依赖:
    venv-doc 环境: python-pptx, pywpsrpc (pip install pywpsrpc)
    系统: WPS Office (wpp 组件), 图形会话 (DISPLAY)
"""
import os
import sys

from pywpsrpc.rpcwppapi import createWppRpcInstance
from pywpsrpc.rpcwppapi import wppapi


def pptx_to_pdf(src: str, dst: str) -> None:
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"输入文件不存在: {src}")
    if not src.lower().endswith((".pptx", ".potx")):
        raise ValueError("输入须为 .pptx/.potx 文件")

    hr, rpc = createWppRpcInstance()
    if hr != 0:
        raise RuntimeError(f"创建 WPS RPC 实例失败 (hr={hr})，请确认 WPS 已安装且图形会话可用")
    hr, app = rpc.getWppApplication()
    if hr != 0:
        raise RuntimeError(f"获取 WPS 应用失败 (hr={hr})")

    try:
        hr, pres = app.Presentations.Open(src)
        if hr != 0:
            raise RuntimeError(f"打开演示文稿失败 (hr={hr})")
        hr = pres.SaveAs(dst, wppapi.PpSaveAsFileType.ppSaveAsPDF)
        if hr != 0:
            raise RuntimeError(f"另存为 PDF 失败 (hr={hr})")
        pres.Close()
    finally:
        app.Quit()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("用法: python convert_to_pdf.py <输入.pptx> <输出.pdf>", flush=True)
        os._exit(2)
    try:
        pptx_to_pdf(sys.argv[1], sys.argv[2])
        print("已转换:", os.path.abspath(sys.argv[2]), flush=True)
        os._exit(0)
    except Exception as e:
        # pywpsrpc 的 SIP 绑定在解释器退出时可能崩溃，直接退出避免 core dump
        print(f"转换失败: {e}", flush=True)
        os._exit(1)
