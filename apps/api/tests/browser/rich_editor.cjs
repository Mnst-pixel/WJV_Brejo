const assert = require('node:assert/strict');
const {resolve, join} = require('node:path');

module.exports = async function richEditorControls(browser, evidence) {
  const context = await browser.newContext({viewport: {width: 390, height: 844}});
  const page = await context.newPage(); const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.route('**/*', route => route.abort());
  const doc = blocks => ({schema: 'kairos-rich-text-v1', blocks});
  const paragraph = (text, marks = {}) => ({type: 'paragraph', content: [{text, ...marks}]});
  async function load(value) {
    await page.setContent('<html lang="pt-BR"><meta name="viewport" content="width=device-width,initial-scale=1"><body><main><form class="panel form"><div class="field"><label for="id_body">Texto</label><textarea id="id_body" name="body" data-rich-seed=""></textarea><input type="hidden" name="rich_document"></div><button type="submit">Salvar rascunho</button></form></main></body></html>');
    await page.locator('textarea').evaluate((element, value) => {element.dataset.richSeed = JSON.stringify(value); element.value = value.blocks.map(block => block.items ? block.items.map(item => item.map(span => span.text).join('')).join('\n') : block.content.map(span => span.text).join('')).join('\n\n').trim();}, value);
    await page.addStyleTag({path: resolve(__dirname, '../../core/static/editorial/workspace.css')});
    await page.addScriptTag({path: resolve(__dirname, '../../core/static/editorial/rich-editor.js')});
  }
  const value = () => page.locator('input[name="rich_document"]').evaluate(element => JSON.parse(element.value));
  async function select(startSelector, start, endSelector, end) {
    await page.evaluate(({startSelector, start, endSelector, end}) => {
      const first = document.createTreeWalker(document.querySelector(startSelector), NodeFilter.SHOW_TEXT).nextNode();
      const last = document.createTreeWalker(document.querySelector(endSelector), NodeFilter.SHOW_TEXT).nextNode();
      const range = document.createRange(); range.setStart(first, start); range.setEnd(last, end);
      const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
    }, {startSelector, start, endSelector, end});
  }
  try {
    const original = doc([paragraph('abcdef', {bold: true, italic: true})]);
    await load(original);
    await select('.visual-editor p', 2, '.visual-editor p', 4);
    await page.getByRole('button', {name: 'Limpar destaque', exact: true}).click();
    assert.deepEqual((await value()).blocks[0].content, [{text: 'ab', bold: true, italic: true}, {text: 'cd'}, {text: 'ef', bold: true, italic: true}]);
    await page.getByRole('button', {name: 'Desfazer formatação', exact: true}).click();
    assert.deepEqual(await value(), original);

    const list = doc([{type: 'bullet_list', items: [[{text: 'first'}], [{text: 'second'}]]}]);
    await load(list);
    await select('.visual-editor li:first-child', 0, '.visual-editor li:last-child', 6);
    await page.getByRole('button', {name: 'Negrito', exact: true}).click();
    assert.deepEqual(await value(), list);

    await load(doc([paragraph('')]));
    const editor = page.getByRole('textbox', {name: 'Texto', exact: true});
    await editor.fill('First paragraph\n\nSecond paragraph');
    const before = await page.locator('textarea').inputValue();
    await editor.press('Control+Home'); await editor.press('Control+Shift+ArrowRight');
    await page.getByRole('button', {name: 'Negrito', exact: true}).click();
    assert.equal(await page.locator('.visual-editor strong').textContent(), 'First ');
    assert.equal(await page.locator('textarea').inputValue(), before);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({path: join(evidence, 'rich-editor-controls-mobile.png'), fullPage: true});

    await load(doc([paragraph('x'.repeat(100000))]));
    await select('.visual-editor p', 0, '.visual-editor p', 100000);
    await page.locator('.visual-editor').evaluate(element => {
      const data = new DataTransfer(); data.setData('text/plain', 'replacement'); data.setData('text/html', '<img src=x onerror=alert(1)>');
      element.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true}));
    });
    assert.equal(await page.locator('textarea').inputValue(), 'replacement');
    assert.equal(await page.locator('.visual-editor img, .visual-editor script').count(), 0);
    assert.deepEqual(errors, []);
    return 'clear-marks-undo-cross-list-root-paragraph-selection-paste-limit-mobile PASS';
  } finally {await context.close();}
};
