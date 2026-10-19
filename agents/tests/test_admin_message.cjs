// Run with Node and Playwright available; no live Sheet/Firebase writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const docs = path.resolve(__dirname, '../../docs');
const files = new Set(['styles.css', 'dashboard_styling.css', 'admin_message.js', 'Consolas.woff2', 'favicon.ico']);
const fixture = fs.readFileSync(path.join(docs, 'dashboard.html'), 'utf8')
    .replace(/<script src="(?!admin_message\.js)[^"]+"><\/script>/g, '');
const server = http.createServer((request, response) => {
    const name = new URL(request.url, 'http://localhost').pathname.slice(1);
    if (!name) {
        response.setHeader('Content-Type', 'text/html; charset=utf-8');
        response.end(fixture);
    } else if (files.has(name)) {
        response.setHeader('Content-Type', name.endsWith('.css') ? 'text/css' : name.endsWith('.js') ? 'text/javascript' : 'application/octet-stream');
        response.end(fs.readFileSync(path.join(docs, name)));
    } else {
        response.writeHead(404).end();
    }
});

async function run() {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const browser = await chromium.launch({
        headless: true,
        executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
    });
    try {
        const page = await browser.newPage({ viewport: { width: 1184, height: 910 } });
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(`http://127.0.0.1:${server.address().port}/`);
        const box = page.locator('#admin-message');
        const content = page.locator('#admin-message-content');
        const update = value => page.evaluate(value => updateAdminMessage(value), value);
        assert.equal(await box.isVisible(), false);
        for (const value of [undefined, null, '', ' \r\n\t ']) {
            await update(value);
            assert.equal(await box.isVisible(), false);
        }

        const message = '# Kedves fűtőközösség!\n\n**Fontos üzenet:**\nA beállítások frissültek.\n\n- Első teendő\n- *Második* teendő\n\n[Leírás](https://example.com/help)';
        await update(message);
        assert.equal(await box.isVisible(), true);
        assert.equal(await content.locator('h3').textContent(), 'Kedves fűtőközösség!');
        assert.equal(await content.locator('strong').textContent(), 'Fontos üzenet:');
        assert.equal(await content.locator('ul li').count(), 2);
        assert.equal(await content.locator('em').textContent(), 'Második');
        assert.match(await content.locator('p').first().textContent(), /\nA beállítások/);
        assert.equal(await box.getByRole('link', { name: 'Kérdésem van' }).getAttribute('href'), 'mailto:markus.benjamin@gmail.com');
        const style = await box.evaluate(element => ({
            background: getComputedStyle(element).backgroundColor,
            border: getComputedStyle(element).borderTopWidth,
            color: getComputedStyle(element).color,
            bounds: element.getBoundingClientRect().toJSON(),
        }));
        assert.equal(style.background, 'rgb(255, 205, 205)');
        assert.equal(style.border, '0px');
        assert.equal(style.color, 'rgb(0, 0, 0)');
        assert.ok(Math.abs(style.bounds.x + style.bounds.width / 2 - 1184 / 2) < 2);
        assert.ok(Math.abs(style.bounds.y + style.bounds.height / 2 - 910 / 2) < 2);
        if (process.env.ADMIN_MESSAGE_SCREENSHOT) {
            await page.screenshot({ path: process.env.ADMIN_MESSAGE_SCREENSHOT });
        }

        await box.getByRole('button', { name: 'Ok', exact: true }).click();
        await update(message);
        assert.equal(await box.isVisible(), false, 'polling must not reopen an acknowledged message');
        await page.reload();
        await update(message);
        assert.equal(await box.isVisible(), false, 'acknowledgement survives reload within the tab');
        await update('Új üzenet');
        assert.equal(await box.isVisible(), true, 'changed message must appear');
        await box.getByRole('button', { name: 'Üzenet bezárása' }).click();
        await update('Új üzenet');
        assert.equal(await box.isVisible(), false, 'X must acknowledge too');
        await update('');
        await update('Új üzenet');
        assert.equal(await box.isVisible(), true, 'clearing and republishing should show the message');
        await page.keyboard.press('Escape');
        assert.equal(await box.isVisible(), false);
        await update('Másik üzenet');
        await update('Új üzenet');
        assert.equal(await box.isVisible(), false, 'the last acknowledged message stays closed');
        await update('Másik üzenet');
        assert.equal(await box.isVisible(), true, 'an unacknowledged message can be shown again');

        await update('<img src=x onerror="window.injected=true">\n\n[Unsafe](javascript:alert(1))\n\n1. Egy\n2. Kettő');
        assert.equal(await content.locator('img, script').count(), 0);
        assert.equal(await content.locator('a').count(), 0);
        assert.equal(await content.locator('ol li').count(), 2);
        assert.equal(await page.evaluate(() => window.injected), undefined);

        await page.setViewportSize({ width: 390, height: 700 });
        await update(('Hosszú üzenet, amelynek el kell férnie kis képernyőn.\n\n').repeat(100));
        const mobile = await box.boundingBox();
        assert.ok(mobile.x >= 0 && mobile.x + mobile.width <= 390);
        assert.ok(mobile.y >= 0 && mobile.y + mobile.height <= 700);
        assert.ok(Math.abs(mobile.x + mobile.width / 2 - 390 / 2) < 2);
        assert.ok(Math.abs(mobile.y + mobile.height / 2 - 700 / 2) < 2);
        assert.ok(await content.evaluate(element => element.scrollHeight > element.clientHeight));
        const okBounds = await box.getByRole('button', { name: 'Ok', exact: true }).boundingBox();
        assert.ok(okBounds.y + okBounds.height <= 700, 'actions stay on screen while content scrolls');
        await box.getByRole('button', { name: 'Ok', exact: true }).click();
        assert.equal(await box.isVisible(), false);
        assert.deepEqual(errors, []);

        const blockedStoragePage = await browser.newPage();
        await blockedStoragePage.addInitScript(() => {
            Object.defineProperty(window, 'sessionStorage', { get() { throw new Error('Storage blocked'); } });
        });
        await blockedStoragePage.goto(`http://127.0.0.1:${server.address().port}/`);
        await blockedStoragePage.evaluate(() => updateAdminMessage('Üzenet tárhely nélkül'));
        await blockedStoragePage.locator('#admin-message-ok').click();
        await blockedStoragePage.evaluate(() => updateAdminMessage('Üzenet tárhely nélkül'));
        assert.equal(await blockedStoragePage.locator('#admin-message').isVisible(), false);
        console.log('Dashboard message browser checks passed (desktop, mobile, formatting, dismissal, storage, safe rendering).');
    } finally {
        await browser.close();
    }
}

run().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => server.close());
