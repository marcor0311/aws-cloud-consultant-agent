"""Render all deliverables and check the standalone deck in an isolated browser."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright


def contact_sheet(paths, destination, width, columns):
    thumbs = []
    for path in paths:
        with Image.open(path) as image:
            copy = image.convert("RGB")
            copy.thumbnail((width, width * 1.5))
            thumbs.append((path.name, copy))
    height = max(image.height for _, image in thumbs) + 32
    sheet = Image.new(
        "RGB",
        (
            columns * (width + 20) + 20,
            ((len(thumbs) + columns - 1) // columns) * (height + 20) + 20,
        ),
        "#dedede",
    )
    draw = ImageDraw.Draw(sheet)
    for i, (name, image) in enumerate(thumbs):
        x, y = 20 + (i % columns) * (width + 20), 20 + (i // columns) * (height + 20)
        draw.text((x, y), name, fill="black")
        sheet.paste(image, (x, y + 25))
    sheet.save(destination)


def verify(directory, qa):
    directory, qa = Path(directory).resolve(), Path(qa).resolve()
    qa.mkdir(parents=True, exist_ok=True)
    pdf_images = []
    pages = {}
    for name in ("resumen-reunion", "ficha-proyecto"):
        pdf = directory / f"{name}.pdf"
        with pymupdf.open(pdf) as doc:
            pages[name] = len(doc)
            if shutil.which("pdftoppm"):
                subprocess.run(
                    ["pdftoppm", "-r", "120", "-png", str(pdf), str(qa / name)],
                    check=True,
                    capture_output=True,
                )
                rendered = sorted(qa.glob(f"{name}-*.png"))
            else:
                rendered = []
                for i, page in enumerate(doc, 1):
                    path = qa / f"{name}-{i}.png"
                    page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(path)
                    rendered.append(path)
            pdf_images.extend(rendered)
    contact_sheet(pdf_images, qa / "pdf-contact.png", 400, 3)

    with sync_playwright() as pw:
        candidates = list(
            (Path.home() / "Library/Caches/ms-playwright").glob(
                "chromium-*/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
            )
        )
        executable = os.getenv("INSUMOS_BROWSER") or (
            str(max(candidates)) if candidates else None
        )
        browser = pw.chromium.launch(headless=True, executable_path=executable)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            reduced_motion="reduce",
            accept_downloads=True,
        )
        context.set_offline(True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((directory / "presentacion.html").as_uri())
        page.evaluate("document.fonts.ready")
        count = page.locator(".slide").count()
        failures = []
        slide_images = []
        for i in range(count):
            page.evaluate("i => window.presentation.show(i)", i)
            page.wait_for_function(
                "getComputedStyle(document.querySelector('.slide.active')).opacity === '1'"
            )
            page.evaluate(
                "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
            )
            geometry = page.evaluate("""() => {
                const slide=document.querySelector('.slide.active');
                const box=slide.getBoundingClientRect(), footer=slide.querySelector('footer').getBoundingClientRect();
                const bad=[...slide.querySelectorAll('.slide-content h2,.slide-content h3,.slide-content p,.slide-content .bottom-note')].filter(el=>{const r=el.getBoundingClientRect();return r.bottom>footer.top-6||r.left<box.left-1||r.right>box.right+1||el.scrollWidth>el.clientWidth+2;}).map(el=>({tag:el.className||el.tagName,text:el.textContent.slice(0,55),bottom:Math.round(el.getBoundingClientRect().bottom),footer:Math.round(footer.top)}));
                const children=[...slide.querySelector('.slide-content').children].filter(el=>!el.matches('.track,.hero-photo,.hero-accent,.hero-lines'));
                for(let i=1;i<children.length;i++){if(children[i].getBoundingClientRect().top<children[i-1].getBoundingClientRect().bottom-1)bad.push({overlap:'content siblings',i});}
                return {ratio:box.width/box.height,bad};
            }""")
            if geometry["bad"] or abs(geometry["ratio"] - 16 / 9) > 0.001:
                failures.append({"slide": i + 1, **geometry})
            path = qa / f"slide-{i + 1:02d}.png"
            page.screenshot(path=str(path), animations="disabled")
            slide_images.append(path)

        page.keyboard.press("Home")
        page.keyboard.press("ArrowRight")
        assert page.locator("#counter").inner_text() == f"02 / {count:02d}"
        page.locator("#prev").click()
        assert page.locator("#counter").inner_text() == f"01 / {count:02d}"
        page.keyboard.press("End")
        assert page.locator("#next").is_disabled()
        page.keyboard.press("Home")
        page.keyboard.press("e")
        assert page.locator("body").evaluate("el => el.classList.contains('editing')")
        title = page.locator(".slide.active [data-edit-id]").first
        title.fill("Texto de revisión local")
        page.locator("#editToggle").click()
        page.reload()
        assert (
            page.locator(".slide.active [data-edit-id]").first.inner_text()
            == "Texto de revisión local"
        )
        page.evaluate("localStorage.clear()")
        page.reload()
        with page.expect_download() as downloaded:
            page.keyboard.press("ControlOrMeta+s")
        downloaded.value.save_as(str(qa / "presentation-export-check.html"))

        page.emulate_media(media="print")
        assert page.locator(".slide:visible").count() == count
        assert not page.locator(".deck-controls").is_visible()
        browser.close()
    contact_sheet(slide_images, qa / "slides-contact.png", 480, 3)
    report = {
        "pdf_pages": pages,
        "slides": count,
        "browser_errors": errors,
        "layout_failures": failures,
        "navigation_editing_export": "passed",
        "offline": True,
    }
    (qa / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors or failures:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="insumos")
    parser.add_argument("--qa", default="/private/tmp/insumos-qa")
    args = parser.parse_args()
    verify(args.directory, args.qa)
