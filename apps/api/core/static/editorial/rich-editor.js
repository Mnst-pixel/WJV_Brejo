/* Small allowlisted document editor. Text is always inserted as text nodes. */
(() => {
  'use strict';
  const schema = 'kairos-rich-text-v1';
  const tags = {paragraph: 'p', heading2: 'h2', heading3: 'h3', quote: 'blockquote', bullet_list: 'ul', ordered_list: 'ol'};
  const kinds = {P: 'paragraph', DIV: 'paragraph', H2: 'heading2', H3: 'heading3', BLOCKQUOTE: 'quote', UL: 'bullet_list', OL: 'ordered_list'};
  for (const textarea of document.querySelectorAll('textarea[name="body"][data-rich-seed]')) {
    const form = textarea.form;
    const hidden = form.querySelector('input[name="rich_document"]');
    if (!hidden) continue;
    const editor = document.createElement('div');
    editor.className = 'visual-editor'; editor.contentEditable = 'true'; editor.role = 'textbox';
    editor.setAttribute('aria-multiline', 'true'); editor.id = textarea.id + '_visual';
    const label = form.querySelector(`label[for="${textarea.id}"]`);
    if (label) {label.id = textarea.id + '_label'; label.htmlFor = editor.id; editor.setAttribute('aria-labelledby', label.id);}
    const notice = document.createElement('p'); notice.className = 'help'; notice.setAttribute('role', 'status');
    const toolbar = document.createElement('div'); toolbar.className = 'visual-toolbar'; toolbar.setAttribute('role', 'group'); toolbar.setAttribute('aria-label', 'Formatação do texto');
    let savedRange = null, dirty = false, undo = null;

    function spans(nodes, marks = {}) {
      const output = [];
      for (const node of nodes) {
        if (node.nodeType === Node.TEXT_NODE) {if (node.textContent) output.push({text: node.textContent, ...marks});}
        else if (node.nodeType === Node.ELEMENT_NODE) {
          if (node.tagName === 'BR') output.push({text: '\n', ...marks});
          else output.push(...spans(node.childNodes, {...marks, ...(['STRONG', 'B'].includes(node.tagName) ? {bold: true} : {}), ...(['EM', 'I'].includes(node.tagName) ? {italic: true} : {})}));
        }
      }
      return output;
    }

    function documentValue() {
      const blocks = []; let pending = [];
      const flush = () => {if (pending.length) {blocks.push({type: 'paragraph', content: spans(pending)}); pending = [];}};
      for (const node of editor.childNodes) {
        if (node.nodeType === Node.ELEMENT_NODE && kinds[node.tagName]) {
          flush();
          if (['UL', 'OL'].includes(node.tagName)) blocks.push({type: kinds[node.tagName], items: [...node.children].map(child => spans(child.childNodes))});
          else blocks.push({type: kinds[node.tagName], content: spans(node.childNodes)});
        } else pending.push(node);
      }
      flush();
      return {schema, blocks: blocks.length ? blocks : [{type: 'paragraph', content: []}]};
    }

    function plain(document) {
      const inline = value => value.map(span => span.text).join('');
      return document.blocks.map(block => block.items ? block.items.map(inline).join('\n') : inline(block.content)).join('\n\n').trim();
    }

    function draw(document) {
      if (document.schema !== schema || !Array.isArray(document.blocks) || document.blocks.length > 1000) throw Error('invalid seed');
      const fragment = window.document.createDocumentFragment();
      function inline(element, values) {
        if (!Array.isArray(values) || values.length > 5000) throw Error('invalid spans');
        for (const span of values) {
          if (typeof span.text !== 'string') throw Error('invalid text');
          let node = window.document.createTextNode(span.text);
          for (const [mark, tag] of [['bold', 'strong'], ['italic', 'em']]) if (span[mark] === true) {const wrap = window.document.createElement(tag); wrap.append(node); node = wrap;}
          element.append(node);
        }
      }
      for (const block of document.blocks) {
        if (!Object.hasOwn(tags, block.type)) throw Error('invalid block');
        const element = window.document.createElement(tags[block.type]);
        if (['bullet_list', 'ordered_list'].includes(block.type)) {
          if (!Array.isArray(block.items) || block.items.length > 1000) throw Error('invalid list');
          for (const item of block.items) {const li = window.document.createElement('li'); inline(li, item); element.append(li);}
        } else inline(element, block.content);
        fragment.append(element);
      }
      editor.replaceChildren(fragment);
    }

    function sync() {
      const value = documentValue(); const text = plain(value);
      textarea.value = text; hidden.value = JSON.stringify(value);
      notice.textContent = text.length > 100000 ? 'O texto excede 100.000 caracteres. Reduza antes de salvar.' : `${text.length.toLocaleString('pt-BR')} caracteres. A formatação será preservada na revisão.`;
      return text.length > 0 && text.length <= 100000 && hidden.value.length <= 600000;
    }

    function range() {
      const selection = getSelection();
      if (selection.rangeCount && editor.contains(selection.getRangeAt(0).commonAncestorContainer)) savedRange = selection.getRangeAt(0).cloneRange();
      if (!savedRange || !editor.contains(savedRange.commonAncestorContainer)) return null;
      return savedRange;
    }

    function select(value) {const selection = getSelection(); selection.removeAllRanges(); selection.addRange(value); savedRange = value.cloneRange(); editor.focus();}
    function remember() {undo = documentValue();}
    function changed() {dirty = true; sync();}
    function button(text, action) {
      const item = document.createElement('button'); item.type = 'button'; item.textContent = text;
      item.addEventListener('pointerdown', event => {range(); event.preventDefault();});
      item.addEventListener('click', action); toolbar.append(item); return item;
    }
    function blockOf(node) {
      let element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
      while (element && element !== editor && element.parentElement !== editor) element = element.parentElement;
      return element === editor ? null : element;
    }
    function textBlock(node) {
      let element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
      while (element && element !== editor) {
        if (['P', 'DIV', 'H2', 'H3', 'BLOCKQUOTE', 'LI'].includes(element.tagName)) return element;
        element = element.parentElement;
      }
      return editor;
    }
    function textOffset(block, container, offset, first = null) {
      const before = document.createRange();
      if (first) before.setStartBefore(first); else before.selectNodeContents(block);
      before.setEnd(container, offset);
      return spans(before.cloneContents().childNodes).map(item => item.text).join('').length;
    }
    function restoreOffsets(block, start, end) {
      const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT); const selected = document.createRange();
      let seen = 0, started = false, node;
      while ((node = walker.nextNode())) {
        const next = seen + node.textContent.length;
        if (!started && start <= next) {selected.setStart(node, start - seen); started = true;}
        if (end <= next) {selected.setEnd(node, end - seen); select(selected); return;}
        seen = next;
      }
      savedRange = null;
    }
    for (const [text, tag] of [['Negrito', 'strong'], ['Itálico', 'em'], ['Limpar destaque', null]]) button(text, () => {
      const selected = range()?.cloneRange();
      if (selected && selected.startContainer === editor && selected.endContainer === editor && selected.endOffset - selected.startOffset === 1) {
        const child = editor.childNodes[selected.startOffset];
        if (child?.nodeType === Node.ELEMENT_NODE && ['P', 'DIV', 'H2', 'H3', 'BLOCKQUOTE'].includes(child.tagName)) selected.selectNodeContents(child);
      }
      let block = selected && textBlock(selected.startContainer);
      if (!selected || selected.collapsed || !block || block !== textBlock(selected.endContainer)) {notice.textContent = 'Selecione um trecho dentro de um mesmo parágrafo ou item de lista.'; return;}
      let nodes = [...block.childNodes], first = null;
      if (block === editor) {
        const top = (node, offset, end) => {if (node === editor) return editor.childNodes[offset - (end ? 1 : 0)]; while (node && node.parentNode !== editor) node = node.parentNode; return node;};
        let left = nodes.indexOf(top(selected.startContainer, selected.startOffset, false)), right = nodes.indexOf(top(selected.endContainer, selected.endOffset, true));
        const structural = node => node?.nodeType === Node.ELEMENT_NODE && kinds[node.tagName];
        if (left < 0 || right < left || nodes.slice(left, right + 1).some(structural)) {notice.textContent = 'Selecione um trecho dentro de um mesmo parágrafo ou item de lista.'; return;}
        while (left > 0 && !structural(nodes[left - 1])) left--;
        while (right < nodes.length - 1 && !structural(nodes[right + 1])) right++;
        nodes = nodes.slice(left, right + 1); first = nodes[0];
      }
      const start = textOffset(block, selected.startContainer, selected.startOffset, first), end = textOffset(block, selected.endContainer, selected.endOffset, first);
      if (start === end) return;
      remember();
      const fragment = document.createDocumentFragment(); let position = 0;
      for (const item of spans(nodes)) {
        const stop = position + item.text.length;
        const cuts = [...new Set([position, Math.max(position, Math.min(stop, start)), Math.max(position, Math.min(stop, end)), stop])].sort((a, b) => a - b);
        for (let index = 0; index < cuts.length - 1; index++) {
          const left = cuts[index], right = cuts[index + 1]; if (left === right) continue;
          const marks = {...item};
          if (left >= start && right <= end) {
            if (tag) marks[tag === 'strong' ? 'bold' : 'italic'] = true;
            else {delete marks.bold; delete marks.italic;}
          }
          let node = document.createTextNode(item.text.slice(left - position, right - position));
          for (const [mark, name] of [['bold', 'strong'], ['italic', 'em']]) if (marks[mark]) {const wrap = document.createElement(name); wrap.append(node); node = wrap;}
          fragment.append(node);
        }
        position = stop;
      }
      if (first) {block = document.createElement('p'); editor.insertBefore(block, first); for (const node of nodes) node.remove();}
      block.replaceChildren(fragment); restoreOffsets(block, start, end); changed();
    });
    const blockLabel = document.createElement('label'); blockLabel.textContent = 'Tipo de parágrafo'; blockLabel.htmlFor = editor.id + '_kind';
    const blockSelect = document.createElement('select'); blockSelect.id = blockLabel.htmlFor;
    for (const [value, text] of [['paragraph', 'Parágrafo'], ['heading2', 'Título de seção'], ['heading3', 'Subtítulo'], ['quote', 'Citação'], ['bullet_list', 'Lista com marcadores'], ['ordered_list', 'Lista numerada']]) {const option = document.createElement('option'); option.value = value; option.textContent = text; blockSelect.append(option);}
    blockSelect.addEventListener('change', () => {
      const selected = range();
      if (!selected || blockOf(selected.startContainer) !== blockOf(selected.endContainer)) {notice.textContent = 'Posicione o cursor em um parágrafo para mudar o formato.'; return;}
      let block = blockOf(selected.startContainer);
      if (!block) {if (editor.childNodes.length > 1) {notice.textContent = 'Selecione um único parágrafo.'; return;} block = document.createElement('p'); block.append(...editor.childNodes); editor.append(block);}
      remember();
      const replacement = document.createElement(tags[blockSelect.value]);
      if (['UL', 'OL'].includes(replacement.tagName)) {
        if (['UL', 'OL'].includes(block.tagName)) replacement.append(...block.childNodes);
        else {const li = document.createElement('li'); li.append(...block.childNodes); replacement.append(li);}
      } else if (['UL', 'OL'].includes(block.tagName)) {
        [...block.children].forEach((li, index) => {if (index) replacement.append(document.createElement('br')); replacement.append(...li.childNodes);});
      } else replacement.append(...block.childNodes);
      block.replaceWith(replacement); const next = document.createRange(); next.selectNodeContents(replacement); next.collapse(false); select(next); changed();
    });
    toolbar.append(blockLabel, blockSelect);
    button('Desfazer formatação', () => {if (!undo) {notice.textContent = 'Nenhuma alteração de formatação para desfazer.'; return;} draw(undo); undo = null; savedRange = null; changed();});

    editor.addEventListener('input', () => {undo = null; changed();});
    editor.addEventListener('keyup', range); editor.addEventListener('pointerup', range); editor.addEventListener('blur', range);
    editor.addEventListener('paste', event => {
      event.preventDefault(); const selected = range(); if (!selected) return;
      const text = event.clipboardData.getData('text/plain');
      const replaced = spans(selected.cloneContents().childNodes).map(item => item.text).join('').length;
      if (text.length + textarea.value.length - replaced > 100000) {notice.textContent = 'A colagem excede o limite de texto.'; return;}
      const node = document.createTextNode(text); selected.deleteContents(); selected.insertNode(node); selected.setStartAfter(node); selected.collapse(true); select(selected); undo = null; changed();
    });
    editor.addEventListener('drop', event => {event.preventDefault(); notice.textContent = 'Cole o texto para inserir conteúdo. Arquivos usam a área de uploads.';});
    try {
      const seed = JSON.parse(textarea.dataset.richSeed || 'null');
      if (!seed || plain(seed) !== textarea.value.trim()) throw Error('plain fallback');
      draw(seed);
    } catch {const paragraph = document.createElement('p'); paragraph.textContent = textarea.value; editor.replaceChildren(paragraph);}
    textarea.hidden = true; textarea.required = false;
    textarea.before(toolbar, editor, notice); sync();
    const beforeUnload = event => {if (dirty) {event.preventDefault(); event.returnValue = '';}};
    window.addEventListener('beforeunload', beforeUnload);
    form.addEventListener('submit', event => {if (!sync()) {event.preventDefault(); notice.textContent = 'Escreva um texto válido de até 100.000 caracteres antes de salvar.'; editor.focus();} else dirty = false;});
  }
})();
