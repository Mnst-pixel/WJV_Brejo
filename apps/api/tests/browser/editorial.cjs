/* Real Next login + Django editorial forms. No session injection, route mocks or production data. */
const {createServer, request} = require('node:http');
const {connect} = require('node:net');
const {createHmac} = require('node:crypto');
const {mkdir, writeFile} = require('node:fs/promises');
const {join} = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.KAIROS_PLAYWRIGHT_MODULE);

function totp(secret) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bits = [...secret].map(c => alphabet.indexOf(c).toString(2).padStart(5, '0')).join('');
  const key = Buffer.from(bits.match(/.{8}/g).map(b => parseInt(b, 2)));
  const time = Buffer.alloc(8); time.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const hash = createHmac('sha1', key).update(time).digest();
  const offset = hash[19] & 15;
  return ((hash.readUInt32BE(offset) & 0x7fffffff) % 1000000).toString().padStart(6, '0');
}

(async () => {
  let raw = ''; for await (const chunk of process.stdin) raw += chunk;
  const config = JSON.parse(raw);
  for (const value of [config.api, config.next]) assert(['localhost', '127.0.0.1'].includes(new URL(value).hostname));
  const proxy = createServer((req, res) => {
    const target = new URL(req.url, req.url.startsWith('/app') ? config.next : config.api);
    const upstream = request(target, {method: req.method, headers: req.headers}, response => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
    });
    upstream.on('error', () => {res.writeHead(502); res.end('Isolated upstream unavailable');}); req.pipe(upstream);
  });
  const upgrades = new Set();
  proxy.on('upgrade', (req, socket, head) => {
    if (!req.url.startsWith('/app/_next/')) return socket.destroy();
    const target = new URL(config.next);
    const upstream = connect(Number(target.port), target.hostname, () => {
      upstream.write(`${req.method} ${req.url} HTTP/1.1\r\n${Object.entries(req.headers).map(([k,v]) => `${k}: ${v}`).join('\r\n')}\r\n\r\n`);
      if (head.length) upstream.write(head);
      socket.pipe(upstream).pipe(socket);
    });
    for (const connection of [socket, upstream]) {
      upgrades.add(connection);
      connection.on('close', () => upgrades.delete(connection));
      connection.on('error', () => {socket.destroy(); upstream.destroy();});
    }
  });
  await new Promise(resolve => proxy.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${proxy.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({headless: true, executablePath: process.env.KAIROS_CHROMIUM_EXECUTABLE, timeout: 15000});
  } catch (error) {
    proxy.close();
    throw error;
  }
  const errors = [];
  const contexts = [];
  await mkdir(config.evidence, {recursive: true});
  async function login(role, viewport = {width: 1440, height: 1000}) {
    const context = await browser.newContext({viewport, reducedMotion: 'reduce'}); contexts.push(context);
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => {
      // Password-only requests must receive428 before the real TOTP challenge succeeds.
      const expectedMfa = message.location().url.endsWith('/api/auth/login') && message.text().includes('428');
      if (message.type() === 'error' && !expectedMfa) errors.push(message.text());
    });
    await page.goto(origin + '/app/entrar/?editorial=1');
    const account = config.principals[role];
    await page.getByLabel('Usuário', {exact: true}).fill(account.username);
    await page.getByLabel('Senha', {exact: true}).fill(account.password);
    const loginResponse = page.waitForResponse(response => response.url().endsWith('/api/auth/login'), {timeout: 10000});
    await page.getByRole('button', {name: 'Entrar', exact: true}).click();
    const passwordResponse = await loginResponse.catch(error => {
      throw new Error(`${error.message}; page=${new URL(page.url()).pathname}; browserErrors=${JSON.stringify(errors)}`);
    });
    assert.equal(passwordResponse.status(), role === 'aluno' ? 200 : 428);
    if (role !== 'aluno') {
      await page.getByLabel('Código do autenticador').fill(totp(account.secret));
      await page.getByRole('button', {name: 'Entrar', exact: true}).click();
      await page.waitForURL('**/admin/editorial/');
      await page.getByRole('heading', {name: 'Painel editorial'}).waitFor();
    } else await page.waitForURL('**/admin/editorial/');
    return page;
  }
  try {
    const editor = await login('editor');
    await editor.getByRole('link', {name: 'Disciplinas e temas', exact: true}).click();
    await editor.getByRole('link', {name: 'Nova disciplina', exact: true}).click();
    await editor.getByLabel('Nome da disciplina').fill('Direito Constitucional');
    await editor.getByRole('button', {name: 'Salvar', exact: true}).click();
    await editor.getByRole('link', {name: 'Conteúdo', exact: true}).click();
    await editor.getByRole('link', {name: 'Criar conteúdo', exact: true}).click();
    await editor.getByLabel('Disciplina').selectOption({label: 'Direito Constitucional'});
    await editor.getByLabel('Título').fill('Direitos fundamentais: roteiro de estudo');
    await editor.getByLabel('Texto').fill('Texto sintético de teste.\n\nA revisão humana verifica a fonte, o marco temporal e os fundamentos.');
    await editor.getByLabel('Link da fonte consultada').fill('https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm');
    await editor.getByRole('button', {name: 'Salvar rascunho', exact: true}).click();
    await editor.getByRole('heading', {name: 'Prévia do conteúdo'}).waitFor();
    await editor.getByLabel('Comentário da decisão').fill('Encaminho a versão para conferência jurídica independente.');
    await editor.getByRole('button', {name: 'Enviar para revisão', exact: true}).click();
    const reviewUrl = editor.url();
    const reviewer = await login('revisor-juridico', {width: 390, height: 844});
    await reviewer.goto(reviewUrl);
    await reviewer.getByLabel('Comentário da decisão').fill('Texto e fonte conferidos no cenário sintético de teste.');
    await reviewer.getByLabel('Situação jurídica verificada').selectOption('current');
    await reviewer.getByRole('button', {name: 'Aprovar revisão', exact: true}).click();
    await reviewer.getByRole('heading', {name: 'Prévia do conteúdo'}).waitFor();
    const approvedUrl = reviewer.url();
    const mobileOverflow = await reviewer.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    assert.equal(mobileOverflow, false);
    await reviewer.screenshot({path: join(config.evidence, 'editorial-mobile.png'), fullPage: true});
    const publisher = await login('administrador-de-conteudo');
    await publisher.goto(approvedUrl);
    await publisher.getByLabel('Comentário da decisão').fill('Publicação da versão aprovada pelo revisor independente.');
    await publisher.getByRole('button', {name: 'Publicar', exact: true}).click();
    await publisher.getByText('Publicado · Versão', {exact: false}).waitFor();
    await publisher.screenshot({path: join(config.evidence, 'editorial-desktop.png'), fullPage: true});
    await publisher.keyboard.press('Tab');
    assert(await publisher.evaluate(() => document.activeElement !== document.body));
    assert(await publisher.evaluate(() => document.fonts.check('400 16px Montserrat')));
    // Student denial is expected and must not be hidden behind a UI-only menu check.
    const studentContext = await browser.newContext(); contexts.push(studentContext);
    const csrf = await (await studentContext.request.get(origin + '/api/auth/csrf')).json();
    const student = config.principals.aluno;
    const signedIn = await studentContext.request.post(origin + '/api/auth/login', {data: {username: student.username, password: student.password}, headers: {'X-CSRFToken': csrf.csrfToken}});
    assert.equal(signedIn.status(), 200);
    const denied = await studentContext.request.get(origin + '/admin/editorial/');
    assert.equal(denied.status(), 403);
    assert.deepEqual(errors, []);
    const result = {workflow: 'PASS', login: 'Next.js password + real TOTP', mobileOverflow, browserErrors: errors,
      studentDenied: denied.status(), viewports: ['1440x1000', '390x844'], productionAccess: false};
    await writeFile(join(config.evidence, 'editorial-browser.json'), JSON.stringify(result, null, 2));
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    const page = contexts[0]?.pages()[0];
    const state = page && !page.isClosed() ? await page.evaluate(() => ({ready: document.readyState, scripts: document.scripts.length, next: typeof window.next, url: location.pathname})).catch(() => null) : null;
    throw new Error(`${error.message}; state=${JSON.stringify(state)}; browserErrors=${JSON.stringify(errors)}`);
  } finally {
    await Promise.all(contexts.map(context => context.close()));
    await browser.close();
    for (const socket of upgrades) socket.destroy();
    proxy.closeAllConnections();
    await new Promise(resolve => proxy.close(resolve));
  }
})().catch(error => {process.stderr.write(error.stack); process.exitCode = 1;});
