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

function acceptsTarget(req, origin) {
  return Boolean(origin && req.url?.startsWith('/') && !req.url.startsWith('//') && !req.url.includes('\\') &&
    req.headers.host === new URL(origin).host && (!req.headers.origin || req.headers.origin === origin));
}

(async () => {
  let raw = ''; for await (const chunk of process.stdin) raw += chunk;
  const config = JSON.parse(raw);
  for (const value of [config.api, config.next]) assert(['localhost', '127.0.0.1'].includes(new URL(value).hostname));
  let origin;
  const proxy = createServer((req, res) => {
    if (!acceptsTarget(req, origin)) {res.writeHead(400); return res.end('Invalid isolated request target');}
    const base = new URL(req.url.startsWith('/app') ? config.next : config.api);
    const target = new URL(req.url, base);
    if (target.origin !== base.origin) {res.writeHead(400); return res.end('Invalid isolated upstream');}
    const upstream = request(target, {method: req.method, headers: req.headers}, response => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res);
    });
    upstream.on('error', () => {res.writeHead(502); res.end('Isolated upstream unavailable');}); req.pipe(upstream);
  });
  const upgrades = new Set();
  proxy.on('upgrade', (req, socket, head) => {
    if (!acceptsTarget(req, origin) || !req.url.startsWith('/app/_next/')) return socket.destroy();
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
  origin = `http://127.0.0.1:${proxy.address().port}`;
  let browser;
  try {
    browser = await chromium.launch({headless: true, executablePath: process.env.KAIROS_CHROMIUM_EXECUTABLE, timeout: 15000});
  } catch (error) {
    proxy.close();
    throw error;
  }
  const errors = [];
  // Close our browser before the Python watchdog so a stalled test cannot orphan it.
  const deadline = setTimeout(() => {void browser.close().catch(() => undefined);}, 140000);
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
    // Real requests prove that even a loopback trap cannot receive forwarded credentials.
    const richEditor = await require('./rich_editor.cjs')(browser, config.evidence);
    let leaked = 0;
    const trap = createServer((req, res) => {leaked += 1; res.end('Unexpected forwarding');});
    await new Promise(resolve => trap.listen(0, '127.0.0.1', resolve));
    try {
      const trapHost = `127.0.0.1:${trap.address().port}`;
      const cases = [
        {path: `http://${trapHost}/leak`}, {path: `//${trapHost}/leak`}, {path: `/\\${trapHost}/leak`},
        {path: '/', headers: {host: 'example.invalid'}}, {path: '/', headers: {origin: 'https://example.invalid'}},
      ];
      for (const entry of cases) {
        const status = await new Promise((resolve, reject) => {
          const probe = request({hostname: '127.0.0.1', port: proxy.address().port, path: entry.path,
            headers: {host: new URL(origin).host, cookie: 'synthetic-probe=not-a-secret', ...entry.headers}}, response => {
              response.resume(); response.on('end', () => resolve(response.statusCode));
            });
          probe.on('error', reject); probe.end();
        });
        assert.equal(status, 400);
      }
      assert.equal(leaked, 0);
    } finally {trap.closeAllConnections(); await new Promise(resolve => trap.close(resolve));}
    const editor = await login('editor');
    await editor.getByRole('link', {name: 'Disciplinas e temas', exact: true}).click();
    await editor.getByRole('link', {name: 'Nova disciplina', exact: true}).click();
    await editor.getByLabel('Nome da disciplina').fill('Direito Constitucional');
    await editor.getByRole('button', {name: 'Salvar', exact: true}).click();
    await editor.getByRole('link', {name: 'Conteúdo', exact: true}).click();
    await editor.getByRole('link', {name: 'Criar conteúdo', exact: true}).click();
    await editor.getByLabel('Disciplina').selectOption({label: 'Direito Constitucional'});
    await editor.getByLabel('Título').fill('Direitos fundamentais: roteiro de estudo');
    await editor.getByRole('textbox', {name: 'Texto:', exact: true}).fill('Texto sintético de teste.\n\nA revisão humana verifica a fonte, o marco temporal e os fundamentos.');
    await editor.getByRole('textbox', {name: 'Texto:', exact: true}).press('Control+Home');
    await editor.getByRole('textbox', {name: 'Texto:', exact: true}).press('Control+Shift+ArrowRight');
    await editor.getByRole('button', {name: 'Negrito', exact: true}).click();
    assert.equal(await editor.locator('.visual-editor strong').textContent(), 'Texto ');
    assert.equal(await editor.locator('textarea[name="body"]').isVisible(), false);
    await editor.setViewportSize({width: 390, height: 844});
    assert.equal(await editor.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await editor.screenshot({path: join(config.evidence, 'rich-editor-mobile.png'), fullPage: true});
    await editor.setViewportSize({width: 1440, height: 1000});
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
    await publisher.getByRole('link', {name: 'Questões e provas', exact: true}).click();
    await publisher.getByRole('link', {name: 'Nova prova ou caderno', exact: true}).click();
    await publisher.getByLabel('Nome da prova ou caderno').fill('Caderno pedagógico de teste');
    await publisher.getByLabel('Organizadora ou autoria').fill('Equipe de teste');
    await publisher.getByLabel('Edição ou identificação do caderno').fill('Teste isolado');
    await publisher.getByLabel('Data da prova ou referência do caderno').fill('2026-09-10');
    await publisher.getByLabel('Fonte da prova ou da autoria').fill('https://example.invalid/caderno');
    await publisher.getByRole('button', {name: 'Salvar prova', exact: true}).click();
    await editor.getByRole('link', {name: 'Questões e provas', exact: true}).click();
    await editor.getByRole('link', {name: 'Nova questão', exact: true}).click();
    await editor.getByLabel('Prova ou caderno').selectOption({label: 'Caderno pedagógico de teste · Teste isolado · 2026'});
    await editor.getByLabel('Disciplina').selectOption({label: 'Direito Constitucional'});
    await editor.getByLabel('Enunciado').fill('No cenário sintético, qual alternativa corresponde ao fundamento apresentado?');
    await editor.getByLabel('Alternativa A', {exact: false}).fill('Primeira opção para o teste.');
    await editor.getByLabel('Alternativa B', {exact: false}).fill('Segunda opção para o teste.');
    await editor.getByLabel('Alternativa correta').selectOption('B');
    await editor.getByLabel('Explicação do gabarito').fill('A segunda alternativa corresponde ao fundamento sintético revisado.');
    await editor.getByLabel('Origem').selectOption('authored');
    await editor.getByLabel('Fonte consultada').fill('https://example.invalid/fundamento');
    await editor.getByLabel('Fundamento jurídico').fill('Fundamento sintético de validação do produto.');
    await editor.getByRole('button', {name: 'Salvar questão como rascunho', exact: true}).click();
    await editor.getByLabel('Comentário da decisão').fill('Conferir enunciado, alternativas, gabarito e fundamento.');
    await editor.getByRole('button', {name: 'Enviar questão para revisão', exact: true}).click();
    await reviewer.goto(editor.url());
    await reviewer.getByLabel('Comentário da decisão').fill('Pacote sintético conferido independentemente.');
    await reviewer.getByLabel('Situação jurídica verificada').selectOption('current');
    await reviewer.getByRole('button', {name: 'Aprovar questão', exact: true}).click();
    await publisher.goto(reviewer.url());
    await publisher.getByLabel('Comentário da decisão').fill('Publicação autorizada para o teste isolado.');
    await publisher.getByRole('button', {name: 'Publicar questão', exact: true}).click();
    await publisher.getByText('Publicado · Versão', {exact: false}).waitFor();
    // Student denial is expected and must not be hidden behind a UI-only menu check.
    const studentContext = await browser.newContext(); contexts.push(studentContext);
    const csrf = await (await studentContext.request.get(origin + '/api/auth/csrf')).json();
    const student = config.principals.aluno;
    const signedIn = await studentContext.request.post(origin + '/api/auth/login', {data: {username: student.username, password: student.password}, headers: {'X-CSRFToken': csrf.csrfToken}});
    assert.equal(signedIn.status(), 200);
    const denied = await studentContext.request.get(origin + '/admin/editorial/');
    assert.equal(denied.status(), 403);
    const learner = await studentContext.newPage();
    learner.on('pageerror', error => errors.push(error.message));
    let expectedLostSave = 0;
    let expectedLostStart = 0;
    let expectedLostNote = 0;
    let expectedLostFlashcard = 0;
    let expectedFlashcardConflict = 0;
    learner.on('console', message => {
      if (message.type() !== 'error') return;
      if (expectedLostSave && message.location().url.endsWith('/autosave/') && message.text().includes('ERR_FAILED')) {expectedLostSave -= 1; return;}
      if (expectedLostStart && message.location().url.endsWith('/simulation-start/') && message.text().includes('ERR_FAILED')) {expectedLostStart -= 1; return;}
      if (expectedLostNote && message.location().url.includes('/api/notes/') && message.text().includes('ERR_FAILED')) {expectedLostNote -= 1; return;}
      if (expectedLostFlashcard && message.location().url.includes('/api/flashcards/') && message.text().includes('ERR_FAILED')) {expectedLostFlashcard -= 1; return;}
      if (expectedFlashcardConflict && message.location().url.includes('/api/flashcards/') && message.text().includes('409')) {expectedFlashcardConflict -= 1; return;}
      errors.push(message.text());
    });
    await learner.setViewportSize({width: 390, height: 844});
    await learner.goto(origin + '/app/estudar');
    await learner.getByRole('button', {name: 'Direitos fundamentais: roteiro de estudo', exact: true}).click();
    await learner.getByRole('heading', {name: 'Direitos fundamentais: roteiro de estudo', exact: true}).waitFor();
    await learner.getByLabel('Leitura concluída (%)').fill('100');
    await learner.getByRole('button', {name: 'Salvar progresso', exact: true}).click();
    await learner.getByText('Progresso confirmado na sua conta.', {exact: true}).waitFor();
    await learner.reload();
    await learner.getByText('Última confirmação: 100%.', {exact: true}).waitFor();
    assert.equal(await learner.getByLabel('Leitura concluída (%)').inputValue(), '100');
    assert.equal(await learner.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await learner.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    await learner.screenshot({path: join(config.evidence, 'reading-mobile.png'), fullPage: true});
    assert.equal(await learner.locator('.rich-text strong').textContent(), 'Texto ');
    const readingUrl = learner.url();
    await learner.getByRole('link', {name: 'Criar anotação desta leitura', exact: true}).click();
    await learner.getByLabel('Texto da anotação', {exact: true}).fill('Minha nota privada.\n\nTexto preservado com espaços finais.  ');
    assert.equal(await learner.getByLabel('Disciplina da anotação', {exact: true}).isDisabled(), true);
    expectedLostNote = 1;
    await learner.route('**/api/notes/', async route => {
      if (route.request().method() !== 'POST') {await route.continue(); return;}
      const saved = await route.fetch(); assert.equal(saved.status(), 201); await route.abort('failed');
    }, {times: 1});
    await learner.getByRole('button', {name: 'Salvar anotação', exact: true}).click();
    await learner.getByRole('button', {name: 'Conferir versão salva', exact: true}).waitFor();
    await learner.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent === 'Conferir versão salva' && !button.disabled));
    assert.equal(expectedLostNote, 0, 'Lost POST was observed before refresh');
    learner.once('dialog', dialog => dialog.accept());
    await learner.reload();
    await learner.getByRole('button', {name: 'Conferir versão salva', exact: true}).click();
    await learner.getByText('A anotação está confirmada na sua conta.', {exact: true}).waitFor();
    assert.equal(expectedLostNote, 0);
    assert.equal(await learner.getByLabel('Texto da anotação', {exact: true}).inputValue(), 'Minha nota privada.\n\nTexto preservado com espaços finais.  ');
    const noteUrl = learner.url();
    let noteList = await (await studentContext.request.get(origin + '/api/notes/')).json();
    assert.equal(noteList.count, 1);
    assert(noteList.results[0].content_version);
    const noteId = noteList.results[0].id;
    await learner.getByLabel('Texto da anotação', {exact: true}).fill('Minha edição confirmada após falha de rede.');
    expectedLostNote = 1;
    await learner.route(`**/api/notes/${noteId}/`, async route => {const saved = await route.fetch(); assert.equal(saved.status(), 200); await route.abort('failed');}, {times: 1});
    await learner.getByRole('button', {name: 'Salvar anotação', exact: true}).click();
    await learner.getByRole('button', {name: 'Conferir versão salva', exact: true}).click();
    await learner.getByText('A anotação está confirmada na sua conta.', {exact: true}).waitFor();
    assert.equal(expectedLostNote, 0);
    await learner.getByLabel('Texto da anotação', {exact: true}).fill('Alteração local ainda não enviada.');
    learner.once('dialog', dialog => dialog.accept());
    await learner.reload();
    await learner.getByRole('button', {name: 'Conferir versão salva', exact: true}).click();
    await learner.getByText('Versão conferida. Suas alterações locais aguardam Salvar anotação.', {exact: true}).waitFor();
    assert.equal(await learner.getByLabel('Texto da anotação', {exact: true}).inputValue(), 'Alteração local ainda não enviada.');
    await learner.getByRole('button', {name: 'Salvar anotação', exact: true}).click();
    await learner.getByText('Anotação salva na sua conta.', {exact: true}).waitFor();
    assert.equal(await learner.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    assert(await learner.locator('.notes-layout .open-row h3').evaluate(element => element.getBoundingClientRect().width > 240));
    await learner.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    await learner.screenshot({path: join(config.evidence, 'personal-notes-mobile.png'), fullPage: true});
    await learner.getByRole('button', {name: 'Leituras publicadas', exact: true}).click();
    await learner.goto(noteUrl);
    await learner.getByRole('heading', {name: 'Editar anotação', exact: true}).waitFor();
    assert.equal(await learner.getByLabel('Texto da anotação', {exact: true}).inputValue(), 'Alteração local ainda não enviada.');
    noteList = await (await studentContext.request.get(origin + '/api/notes/')).json();
    assert.equal(noteList.count, 1); assert.equal(noteList.results[0].version, 3);
    const flashcardsWorkflow = await require('./flashcards.cjs')(learner, studentContext, origin, config.evidence, kind => {if (kind === 'conflict') expectedFlashcardConflict += 1; else expectedLostFlashcard += 1;});
    assert.equal(expectedLostFlashcard, 0);
    assert.equal(expectedFlashcardConflict, 0);
    await learner.goto(readingUrl);
    await learner.getByRole('heading', {name: 'Direitos fundamentais: roteiro de estudo', exact: true}).waitFor();
    await learner.getByRole('link', {name: 'Praticar esta disciplina', exact: true}).click();
    await learner.waitForURL('**/app/questoes?subject=*');
    const linkedSubject = new URL(learner.url()).searchParams.get('subject');
    await learner.getByRole('heading', {name: 'No cenário sintético, qual alternativa corresponde ao fundamento apresentado?'}).waitFor();
    assert.equal(await learner.getByLabel('Disciplina', {exact: true}).inputValue(), linkedSubject);
    await learner.goto(origin + '/app/questoes');
    await learner.getByRole('heading', {name: 'No cenário sintético, qual alternativa corresponde ao fundamento apresentado?'}).waitFor();
    assert.equal(await learner.getByText('A segunda alternativa corresponde ao fundamento sintético revisado.', {exact: true}).count(), 0);
    await learner.getByRole('radio', {name: 'B Segunda opção para o teste.'}).check();
    await learner.getByRole('button', {name: 'Responder', exact: true}).click();
    await learner.getByRole('heading', {name: 'Resposta correta', exact: true}).waitFor();
    await learner.getByRole('button', {name: 'Salvar favorita', exact: true}).click();
    await learner.getByRole('button', {name: 'Remover favorita', exact: true}).waitFor();
    await learner.getByRole('button', {name: 'Marcar para revisão', exact: true}).click();
    await learner.getByRole('button', {name: 'Retirar da revisão', exact: true}).waitFor();
    await learner.reload();
    await learner.getByRole('button', {name: 'Remover favorita', exact: true}).waitFor();
    await learner.getByRole('button', {name: 'Retirar da revisão', exact: true}).waitFor();
    await learner.getByText('Acerto ·', {exact: false}).waitFor();
    assert(await learner.locator('.open-row h3').evaluate(element => element.getBoundingClientRect().width > 250));
    assert.equal(await learner.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await learner.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    assert(await learner.locator('.skip-link').evaluate(element => element.getBoundingClientRect().bottom < 0));
    await learner.screenshot({path: join(config.evidence, 'practice-mobile.png'), fullPage: true});
    await learner.setViewportSize({width: 1440, height: 1000});
    await learner.screenshot({path: join(config.evidence, 'practice-desktop.png'), fullPage: true});
    await learner.goto(origin + '/app/simulados');
    expectedLostStart = 1;
    await learner.route('**/api/simulation-start/', async route => {
      const committed = await route.fetch();
      assert.equal(committed.status(), 201);
      await route.abort('failed');
    }, {times: 1});
    await learner.getByRole('button', {name: 'Iniciar simulado', exact: true}).click();
    await learner.getByText('Não foi possível confirmar a conexão com o servidor.', {exact: false}).waitFor();
    await learner.reload();
    await learner.getByRole('button', {name: 'Confirmar preparação anterior', exact: true}).click();
    assert.equal(expectedLostStart, 0);
    await learner.getByRole('heading', {name: 'Meu simulado', exact: true, level: 2}).waitFor();
    await learner.getByRole('radio', {name: 'B Segunda opção para o teste.'}).check();
    await learner.getByText('Respostas salvas na sua conta.', {exact: true}).waitFor();
    const simulationUrl = learner.url();
    // Real backend commits, but the browser loses the response; reload must reconcile it.
    expectedLostSave = 1;
    await learner.route('**/api/attempts/*/autosave/', async route => {
      const committed = await route.fetch();
      assert.equal(committed.status(), 200);
      await route.abort('failed');
    }, {times: 1});
    await learner.getByRole('button', {name: 'Revisar esta questão antes de enviar', exact: true}).click();
    await learner.getByText('Salvamento não confirmado.', {exact: false}).waitFor();
    learner.once('dialog', dialog => dialog.accept());
    await learner.reload();
    await learner.getByRole('heading', {name: 'Meu simulado', exact: true, level: 2}).waitFor();
    assert(await learner.getByRole('radio', {name: 'B Segunda opção para o teste.'}).isChecked());
    assert(await learner.getByRole('button', {name: 'Retirar marca de revisão', exact: true}).getAttribute('aria-pressed') === 'true');
    assert.equal(expectedLostSave, 0);
    assert.equal(learner.url(), simulationUrl);
    await learner.getByRole('button', {name: 'Finalizar simulado', exact: true}).click();
    await learner.getByRole('heading', {name: 'Confirmar envio final', exact: true}).waitFor();
    await learner.getByRole('button', {name: 'Confirmar finalização', exact: true}).click();
    await learner.getByRole('heading', {name: 'Resultado do simulado', exact: true}).waitFor();
    await learner.getByText('1 de 1 acertos', {exact: true}).waitFor();
    await learner.setViewportSize({width: 390, height: 844});
    assert.equal(await learner.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await learner.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    await learner.screenshot({path: join(config.evidence, 'simulation-result-mobile.png'), fullPage: true});
    await editor.goto(origin + '/admin/editorial/segunda-fase/');
    await editor.getByRole('link', {name: 'Criar área', exact: true}).click();
    await editor.getByLabel('Nome da área').fill('Direito Civil');
    await editor.getByRole('button', {name: 'Criar área', exact: true}).click();
    await editor.getByRole('link', {name: 'Criar caderno de segunda fase', exact: true}).click();
    await editor.getByLabel('Nome da prova ou caderno').fill('Escrita pedagógica de teste');
    await editor.getByLabel('Organizadora ou autoria').fill('Equipe de teste');
    await editor.getByLabel('Edição ou identificação do caderno').fill('Segunda fase isolada');
    await editor.getByLabel('Data da prova ou referência do caderno').fill('2026-09-10');
    await editor.getByLabel('Fonte da prova ou da autoria').fill('https://example.invalid/segunda-fase');
    await editor.getByRole('button', {name: 'Criar caderno', exact: true}).click();
    await editor.getByRole('link', {name: 'Criar caso e espelho', exact: true}).click();
    await editor.getByLabel('Prova ou caderno').selectOption({label: 'Escrita pedagógica de teste · Segunda fase isolada · 2026'});
    await editor.getByLabel('Área da segunda fase').selectOption({label: 'Direito Civil'});
    await editor.getByLabel('Título do caso').fill('Caso prático de escrita');
    await editor.getByLabel('Peça cabível', {exact: false}).fill('Peça reservada ao espelho');
    await editor.getByLabel('Enunciado apresentado ao aluno').fill('Redija a peça adequada ao caso sintético apresentado.');
    await editor.getByLabel('Fonte consultada').fill('https://example.invalid/fonte-escrita');
    await editor.getByRole('button', {name: 'Adicionar discursiva', exact: true}).click();
    const discursive = editor.locator('[data-formset="questions"] [data-row]').first();
    await discursive.getByLabel('Questão').selectOption('Q1');
    await discursive.getByLabel('Enunciado').fill('Explique o fundamento do caso sintético.');
    await discursive.getByLabel('Padrão de resposta reservado').fill('Padrão reservado da questão de teste.');
    for (const [code, target, title] of [['P1', 'piece', 'Estrutura da peça'], ['D1', 'Q1', 'Fundamento da discursiva']]) {
      await editor.getByRole('button', {name: 'Adicionar critério', exact: true}).click();
      const criterion = editor.locator('[data-formset="criteria"] [data-row]').last();
      await criterion.getByLabel('Referência curta do critério').fill(code);
      await criterion.getByLabel('Grupo do espelho').fill('Fundamentos');
      await criterion.getByLabel('Resposta avaliada').selectOption(target);
      await criterion.getByLabel('Nome do critério').fill(title);
      await criterion.getByLabel('O que deve ser avaliado').fill('Critério sintético individual para conferência.');
      await criterion.getByLabel('Pontos máximos').fill('5');
    }
    const criterionRows = editor.locator('[data-formset="criteria"] [data-row]');
    await criterionRows.last().getByRole('button', {name: 'Mover item para cima'}).click();
    assert.equal(await criterionRows.first().getByLabel('Referência curta do critério').inputValue(), 'D1');
    await criterionRows.first().getByRole('button', {name: 'Mover item para baixo'}).click();
    assert.equal(await criterionRows.first().getByLabel('Referência curta do critério').inputValue(), 'P1');
    await editor.getByRole('button', {name: 'Salvar caso como rascunho', exact: true}).click();
    await editor.getByRole('heading', {name: 'Espelho reservado', exact: true}).waitFor();
    await editor.getByLabel(/^Decisão:?$/).selectOption('review');
    await editor.getByLabel('Comentário da decisão').fill('Conferir o caso e cada critério do espelho.');
    await editor.getByRole('button', {name: 'Registrar decisão', exact: true}).click();
    await reviewer.goto(editor.url());
    await reviewer.getByLabel(/^Decisão:?$/).selectOption('approved');
    await reviewer.getByLabel('Comentário da decisão').fill('Caso, discursiva e critérios conferidos independentemente.');
    await reviewer.getByLabel('Situação jurídica conferida', {exact: false}).selectOption('current');
    await reviewer.getByRole('button', {name: 'Registrar decisão', exact: true}).click();
    await publisher.goto(reviewer.url());
    await publisher.getByLabel(/^Decisão:?$/).selectOption('published');
    await publisher.getByLabel('Comentário da decisão').fill('Publicar pacote revisado da segunda fase.');
    await publisher.getByRole('button', {name: 'Registrar decisão', exact: true}).click();
    await publisher.getByText('Publicado · Versão', {exact: false}).waitFor();
    await learner.goto(origin + '/app/segunda-fase');
    await learner.getByRole('button', {name: 'Redigir prova', exact: true}).click();
    await learner.getByLabel('Sua peça profissional', {exact: true}).waitFor();
    assert.equal(await learner.getByText('Peça reservada ao espelho', {exact: true}).count(), 0);
    const writtenText = 'Peça sintética preservada.\n\n' + 'Fundamento e pedido. '.repeat(200);
    expectedLostSave = 1;
    await learner.route('**/api/phase2/submissions/*/autosave/', async route => {const committed = await route.fetch(); assert.equal(committed.status(), 200); await route.abort('failed');}, {times: 1});
    await learner.getByLabel('Sua peça profissional', {exact: true}).fill(writtenText);
    await learner.getByText('Salvamento não confirmado.', {exact: false}).waitFor();
    learner.once('dialog', dialog => dialog.accept());
    await learner.reload();
    await learner.getByLabel('Sua peça profissional', {exact: true}).waitFor();
    assert.equal(await learner.getByLabel('Sua peça profissional', {exact: true}).inputValue(), writtenText);
    assert.equal(expectedLostSave, 0);
    await learner.getByRole('button', {name: 'Questão 1', exact: true}).click();
    await learner.getByLabel('Sua resposta à questão 1', {exact: true}).fill('Resposta discursiva que permanece na conta.');
    await learner.getByText('Texto salvo na sua conta.', {exact: true}).waitFor();
    await learner.getByRole('button', {name: 'Enviar prova', exact: true}).click();
    await learner.getByRole('button', {name: 'Confirmar envio final', exact: true}).click();
    await learner.getByText('Prova enviada. Seus textos foram preservados', {exact: false}).waitFor();
    assert.equal(await learner.getByLabel('Sua resposta à questão 1').getAttribute('readonly'), '');
    assert.equal(await learner.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await learner.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    assert(await learner.locator('.skip-link').evaluate(element => element.getBoundingClientRect().bottom < 0));
    await learner.screenshot({path: join(config.evidence, 'phase2-submitted-mobile.png'), fullPage: true});
    await learner.goto(origin + '/app');
    await learner.getByText('1 de 1 leituras concluídas na versão atual', {exact: true}).waitFor();
    await learner.getByText('2 acertos em 2 respostas (100%).', {exact: false}).waitFor();
    await learner.getByLabel('Período', {exact: true}).selectOption('30');
    await learner.getByText('2 acertos em 2 respostas (100%).', {exact: false}).waitFor();
    await learner.getByText('Ver valores por dia e disciplina', {exact: true}).click();
    assert.equal(await learner.locator('.learning-table tbody tr').count(), 30);
    assert.equal(await learner.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await learner.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
    await learner.screenshot({path: join(config.evidence, 'learning-dashboard-mobile.png'), fullPage: true});
    const accountAdmin = await login('administrador', {width: 390, height: 844});
    await accountAdmin.getByRole('link', {name: 'Usuários', exact: true}).click();
    await accountAdmin.getByRole('link', {name: 'Criar usuário', exact: true}).click();
    await accountAdmin.getByLabel('Nome da pessoa').fill('Pessoa cadastrada pelo painel');
    await accountAdmin.getByLabel('Nome de acesso').fill('pessoa-nova-browser');
    await accountAdmin.getByLabel('E-mail para acesso').fill('new-learner@example.invalid');
    await accountAdmin.getByLabel('Motivo da alteração').fill('Cadastro sintético para validar a operação leiga.');
    await accountAdmin.getByRole('button', {name: 'Criar conta', exact: true}).click();
    await accountAdmin.getByRole('heading', {name: 'Pessoa cadastrada pelo painel', exact: true}).waitFor();
    const accountUrl = accountAdmin.url();
    assert.equal((await studentContext.request.get(accountUrl)).status(), 403);
    assert.equal((await editor.request.get(accountUrl)).status(), 403);
    await accountAdmin.getByRole('link', {name: 'Editar cadastro', exact: true}).click();
    await accountAdmin.getByLabel('Nome da pessoa').fill('Pessoa com cadastro revisado');
    await accountAdmin.getByLabel('Motivo da alteração').fill('Conferência cadastral autorizada para o teste.');
    await accountAdmin.getByRole('button', {name: 'Salvar cadastro', exact: true}).click();
    await accountAdmin.getByRole('link', {name: 'Administrar papéis', exact: true}).click();
    await accountAdmin.getByLabel('Aluno', {exact: true}).uncheck();
    await accountAdmin.getByLabel('Editor', {exact: true}).check();
    assert.equal(await accountAdmin.getByLabel('Superadministrador', {exact: true}).count(), 0);
    await accountAdmin.getByLabel('Motivo da alteração').fill('Conceder função editorial limitada, sem publicação.');
    await accountAdmin.getByRole('button', {name: 'Salvar papéis', exact: true}).click();
    for (const action of ['disable', 'enable', 'revoke', 'access']) {
      await accountAdmin.getByRole('combobox', {name: 'Ação:', exact: true}).selectOption(action);
      await accountAdmin.getByLabel('Motivo da alteração').fill('Validar alteração auditada de acesso no teste isolado.');
      await accountAdmin.getByRole('button', {name: 'Aplicar ação de acesso', exact: true}).click();
      await accountAdmin.getByRole('heading', {name: 'Pessoa com cadastro revisado', exact: true}).waitFor();
    }
    await accountAdmin.getByText('Envio indisponível: o serviço de e-mail ainda não foi configurado.', {exact: true}).waitFor();
    assert.equal(await accountAdmin.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await accountAdmin.screenshot({path: join(config.evidence, 'accounts-mobile.png'), fullPage: true});
    await accountAdmin.getByRole('link', {name: 'Assinaturas', exact: true}).click();
    const subscriptionsUrl = accountAdmin.url();
    assert.equal((await studentContext.request.get(subscriptionsUrl)).status(), 403);
    assert.equal((await editor.request.get(subscriptionsUrl)).status(), 403);
    await accountAdmin.getByRole('link', {name: 'Criar plano', exact: true}).click();
    await accountAdmin.getByLabel('Nome:', {exact: true}).fill('Plano OAB pelo painel');
    await accountAdmin.getByLabel('Tamanho máximo de cada arquivo').fill('5');
    await accountAdmin.getByLabel('Espaço por pessoa').fill('50');
    await accountAdmin.getByLabel('Ativo:', {exact: true}).check();
    await accountAdmin.getByLabel('Motivo da alteração').fill('Plano de estudo sintético com limites revisados.');
    assert.equal(await accountAdmin.locator('input[name="code"]').count(), 0);
    await accountAdmin.getByRole('button', {name: 'Salvar plano', exact: true}).click();
    await accountAdmin.getByRole('heading', {name: 'Plano OAB pelo painel', exact: true}).waitFor();
    await accountAdmin.goto(accountUrl);
    await accountAdmin.getByRole('link', {name: 'Administrar plano', exact: true}).click();
    await accountAdmin.getByLabel('Plano:', {exact: true}).selectOption({label: 'Plano OAB pelo painel'});
    await accountAdmin.getByLabel('Início da validade').fill('2026-01-01T09:00');
    await accountAdmin.getByLabel('Estado da matrícula').selectOption('active');
    await accountAdmin.getByLabel('Motivo da alteração').fill('Vincular pessoa ao plano revisado para o teste.');
    await accountAdmin.getByRole('button', {name: 'Salvar matrícula', exact: true}).click();
    await accountAdmin.getByText('Matrícula salva. A titularidade e os arquivos existentes foram preservados.', {exact: true}).waitFor();
    await accountAdmin.getByLabel('Estado da matrícula').selectOption('suspended');
    await accountAdmin.getByLabel('Motivo da alteração').fill('Validar suspensão sem excluir o cadastro ou os arquivos.');
    await accountAdmin.getByRole('button', {name: 'Salvar matrícula', exact: true}).click();
    await accountAdmin.getByText('Matrícula salva. A titularidade e os arquivos existentes foram preservados.', {exact: true}).waitFor();
    await accountAdmin.getByRole('link', {name: 'Assinaturas', exact: true}).click();
    await accountAdmin.getByLabel('Buscar pessoa ou plano').fill('Plano OAB pelo painel');
    await accountAdmin.getByRole('button', {name: 'Buscar matrículas', exact: true}).click();
    await accountAdmin.getByText('Plano indisponível para novos uploads.', {exact: true}).waitFor();
    assert.equal(await accountAdmin.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await accountAdmin.screenshot({path: join(config.evidence, 'subscriptions-mobile.png'), fullPage: true});
    await accountAdmin.getByRole('link', {name: 'Limites gerais de arquivos', exact: true}).click();
    await accountAdmin.getByLabel('Permitir novos uploads').check();
    await accountAdmin.getByLabel('Tamanho máximo de cada arquivo').fill('10');
    await accountAdmin.getByLabel('Espaço por pessoa').fill('100');
    await accountAdmin.getByLabel('Motivo da alteração').fill('Conferir limites globais sem tocar arquivos privados.');
    await accountAdmin.getByRole('button', {name: 'Salvar limites', exact: true}).click();
    await accountAdmin.getByText('Limites gerais salvos. Arquivos existentes permanecem preservados.', {exact: true}).waitFor();
    assert.deepEqual(errors, []);
    const result = {workflow: 'PASS', richEditor, flashcardsWorkflow, subscriptionsWorkflow: 'plan-enrollment-suspend-search-global-limits PASS', accountsWorkflow: 'create-edit-roles-disable-enable-revoke-smtp-state PASS', readingWorkflow: 'published-read-progress-refresh-discipline-practice-dashboard-period PASS', phase2Workflow: 'case-rubric-review-publish-write-lost-autosave-reload-submit PASS', questionWorkflow: 'author-review-publish-answer-history-marks-reload PASS', simulationWorkflow: 'start-answer-autosave-lost-response-review-mark-refresh-resume-submit-grade PASS', login: 'Next.js password + real TOTP', mobileOverflow, browserErrors: errors,
      studentDenied: denied.status(), proxyExfiltration: '5 rejected; trap received zero requests', viewports: ['1440x1000', '390x844'], productionAccess: false};
    await writeFile(join(config.evidence, 'editorial-browser.json'), JSON.stringify(result, null, 2));
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    const page = contexts[0]?.pages()[0];
    const state = page && !page.isClosed() ? await page.evaluate(() => ({ready: document.readyState, scripts: document.scripts.length, next: typeof window.next, url: location.pathname})).catch(() => null) : null;
    throw new Error(`${error.message}; state=${JSON.stringify(state)}; browserErrors=${JSON.stringify(errors)}`);
  } finally {
    clearTimeout(deadline);
    await Promise.all(contexts.map(context => context.close()));
    await browser.close();
    for (const socket of upgrades) socket.destroy();
    proxy.closeAllConnections();
    await new Promise(resolve => proxy.close(resolve));
  }
})().catch(error => {process.stderr.write(error.stack); process.exitCode = 1;});
