import sys, asyncio
from pathlib import Path
from playwright.async_api import async_playwright
SP = Path("/tmp/claude-0/-home-user-CarlosPVSolarTest/5c49453f-37f7-57ac-9ed8-5fcab4df3410/scratchpad")
LIB = {"d3.min.js": SP / "d3.min.js", "topojson.min.js": SP / "topojson.min.js"}

async def run(html, tag, width):
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
        pg = await b.new_page(viewport={"width": width, "height": 900})
        errs = []
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append(str(e)))
        async def route(r):
            name = r.request.url.split("/")[-1]
            await r.fulfill(path=str(LIB[name]), content_type="application/javascript")
        await pg.route("https://cdnjs.cloudflare.com/**", route)
        await pg.goto("file://" + str(Path(html).resolve()))
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=str(SP / f"{tag}_{width}_top.png"), full_page=False)
        await pg.screenshot(path=str(SP / f"{tag}_{width}_full.png"), full_page=True)
        n = await pg.evaluate("document.querySelectorAll('circle.dot').length")
        # interactions
        await pg.click("#controls .ctl:nth-child(6) .seg button:nth-child(1)")   # month granularity
        await pg.wait_for_timeout(400)
        await pg.select_option("#controls .ctl:nth-child(3) select", label="TX")
        await pg.wait_for_timeout(400)
        n_tx = await pg.evaluate("document.querySelectorAll('circle.dot').length")
        await pg.click("#rowmode button:nth-child(2)"); await pg.wait_for_timeout(300)
        await pg.click("#grid tbody tr:first-child"); await pg.wait_for_timeout(400)
        drill = await pg.evaluate("document.querySelectorAll('#grid tbody tr').length")
        await pg.click("#back"); await pg.wait_for_timeout(300)
        await pg.click("#rowmode button:nth-child(3)"); await pg.wait_for_timeout(300)
        if tag == "bess":
            await pg.click("#chartmode button:nth-child(2)"); await pg.wait_for_timeout(400)
        await pg.screenshot(path=str(SP / f"{tag}_{width}_interact.png"), full_page=True)
        await pg.click("text=Reset all"); await pg.wait_for_timeout(500)
        await pg.locator("circle.dot").last.click(force=True); await pg.wait_for_timeout(500)
        pinned = await pg.evaluate("document.querySelectorAll('#grid tbody tr').length")
        sw = await pg.evaluate("document.documentElement.scrollWidth")
        print(tag, width, "dots", n, "TX dots", n_tx, "drill rows", drill, "pinned rows", pinned, "scrollWidth", sw, "errors", errs[:5])
        await b.close()

asyncio.run(run(sys.argv[1], sys.argv[2], int(sys.argv[3])))
