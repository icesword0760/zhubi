#!/usr/bin/env python3
"""重新生成 README 用的截图和演示 GIF。

前提：朱笔已在 http://127.0.0.1:8003 运行，且存在名为 PROJECT 的已标注项目。
用法：python scripts/capture_assets.py [--base http://127.0.0.1:8003] [--project 垂直图标训练]
输出：assets/*.png 与 assets/hero-raw.webm（再用 ffmpeg 转成 assets/hero.gif）
"""
import argparse
import re
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def zoom_to(page, target=0.45):
    """点「缩小」直到画布缩放不超过 target，返回实际缩放比例。"""
    for _ in range(12):
        text = page.locator("#zoomLevel").inner_text().strip().rstrip("%")
        zoom = float(text) / 100
        if zoom <= target:
            return zoom
        page.evaluate("zoomOut()")
        page.wait_for_timeout(150)
    return zoom


def open_annotate(page, base, project):
    page.goto(f"{base}/")
    page.wait_for_selector(".project-card")
    card = page.locator(".project-card", has_text=project).first
    card.get_by_role("button", name="标注").click()
    page.wait_for_selector("#annotationCanvas")
    page.wait_for_timeout(1500)


def capture_screens(base, project):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, locale="zh-CN")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())

        # 1. 项目列表
        page.goto(f"{base}/")
        page.wait_for_selector(".project-card")
        page.wait_for_timeout(500)
        page.screenshot(path=str(ASSETS / "projects.png"), clip={"x": 0, "y": 0, "width": 1440, "height": 470})

        # 2. 标注页：缩放到能同时看到工具栏、图片上的框和右侧列表
        page.set_viewport_size({"width": 1440, "height": 1150})
        open_annotate(page, base, project)
        zoom_to(page, 0.45)
        page.wait_for_timeout(400)
        page.screenshot(path=str(ASSETS / "annotate.png"))
        page.set_viewport_size({"width": 1440, "height": 900})

        # 3. 导出页：选项目 + YOLO 格式
        page.goto(f"{base}/export.html")
        page.wait_for_function("document.querySelectorAll('#projectSelect option').length > 1")
        page.select_option("#projectSelect", value=project)
        page.wait_for_timeout(800)
        page.locator(".format-card", has_text="YOLO").first.click()
        page.wait_for_timeout(300)
        page.evaluate("window.scrollTo(0, 120)")
        page.screenshot(path=str(ASSETS / "export.png"))

        # 4. 训练页：配置区 + 已训练模型
        page.goto(f"{base}/train.html")
        page.wait_for_selector("#modelsList")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(ASSETS / "train.png"), clip={"x": 0, "y": 100, "width": 1440, "height": 640})
        models = page.locator("#modelsList")
        models.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        models.screenshot(path=str(ASSETS / "models.png"))
        ctx.close()
        browser.close()


def record_hero(base, project):
    """录一段真实速度的标注故事：进项目 → 拖框 → 保存并继续 → 下一张 → 去导出。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=str(ASSETS / "_video"),
            record_video_size={"width": 1280, "height": 800},
            locale="zh-CN",
        )
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        page.goto(f"{base}/")
        page.wait_for_selector(".project-card")
        page.wait_for_timeout(1200)
        card = page.locator(".project-card", has_text=project).first
        card.get_by_role("button", name="标注").hover()
        page.wait_for_timeout(400)
        card.get_by_role("button", name="标注").click()
        page.wait_for_selector("#annotationCanvas")
        page.wait_for_timeout(1500)
        zoom = zoom_to(page, 0.45)
        page.wait_for_timeout(600)
        # 把图标区域滚进视口
        page.mouse.wheel(0, 420)
        page.wait_for_timeout(600)
        box = page.locator("#annotationCanvas").bounding_box()
        # 图标大约在原图 (470..690, 1840..2070) 的位置
        x1, y1 = box["x"] + 462 * zoom, box["y"] + 1836 * zoom
        x2, y2 = box["x"] + 700 * zoom, box["y"] + 2080 * zoom
        page.mouse.move(x1, y1)
        page.wait_for_timeout(300)
        page.mouse.down()
        steps = 18
        for i in range(1, steps + 1):
            page.mouse.move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
            page.wait_for_timeout(35)
        page.mouse.up()
        page.wait_for_timeout(900)
        page.get_by_role("button", name=re.compile("保存并继续")).click()
        page.wait_for_timeout(1800)
        page.get_by_role("link", name="数据导出").click()
        page.wait_for_function("document.querySelectorAll('#projectSelect option').length > 1")
        page.wait_for_timeout(600)
        page.select_option("#projectSelect", value=project)
        page.wait_for_timeout(700)
        page.locator(".format-card", has_text="YOLO").first.click()
        page.wait_for_timeout(1200)
        video = page.video
        ctx.close()
        browser.close()
        src = Path(video.path())
        shutil.move(src, ASSETS / "hero-raw.webm")
        shutil.rmtree(ASSETS / "_video", ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8003")
    ap.add_argument("--project", default="垂直图标训练")
    ap.add_argument("--only", choices=["screens", "hero"], default=None)
    args = ap.parse_args()
    ASSETS.mkdir(exist_ok=True)
    if args.only in (None, "screens"):
        capture_screens(args.base, args.project)
    if args.only in (None, "hero"):
        record_hero(args.base, args.project)
    print("done")
