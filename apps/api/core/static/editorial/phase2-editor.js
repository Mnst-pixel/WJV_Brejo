"use strict";
(() => {
  const editor = document.querySelector("#case-editor");
  if (!editor) return;
  let dragged = null;
  const rows = section => [...section.querySelector("[data-rows]").children];
  const reorder = section => rows(section).forEach((row, i) => {row.querySelector('[name$="-ORDER"]').value = String(i + 1);});
  function update() {
    const section = editor.querySelector('[data-formset="criteria"]');
    const items = rows(section).filter(row => !row.querySelector('[name$="-DELETE"]').checked);
    const cents = items.reduce((total, row) => {
      const raw = row.querySelector('[name$="-max_points"]').value.replace(",", ".");
      return total + (/^\d+(\.\d{1,2})?$/.test(raw) ? Math.round(Number(raw) * 100) : 0);
    }, 0);
    editor.querySelector("#rubric-total").textContent = `Soma em edição: ${(cents / 100).toLocaleString("pt-BR", {minimumFractionDigits: 2})} pontos. A aprovação confere a soma no servidor.`;
    const choices = items.map(row => [row.querySelector('[name$="-code"]').value, row.querySelector('[name$="-title"]').value]).filter(([code]) => code);
    items.forEach(row => {
      const select = row.querySelector('[name$="-dependencies"]');
      const selected = [...select.selectedOptions].map(option => option.value);
      const preserved = [...choices, ...selected.filter(code => !choices.some(([value]) => value === code)).map(code => [code, "Referência anterior: confira o vínculo antes de salvar"] )];
      select.replaceChildren(...preserved.map(([code, title]) => {const option = document.createElement("option"); option.value = code; option.textContent = `${code} — ${title}`; option.selected = selected.includes(code); return option;}));
    });
  }
  editor.querySelectorAll("[data-formset]").forEach(section => {
    const prefix = section.dataset.formset;
    const total = section.querySelector(`[name="${prefix}-TOTAL_FORMS"]`);
    section.querySelector("[data-add]").addEventListener("click", () => {
      const index = Number(total.value);
      if (index >= Number(section.dataset.limit)) return;
      const template = document.createElement("template");
      template.innerHTML = section.querySelector("template").innerHTML.replaceAll("__prefix__", String(index));
      const row = template.content.firstElementChild;
      section.querySelector("[data-rows]").append(row);
      total.value = String(index + 1); reorder(section); update();
      row.querySelector("input,select,textarea")?.focus();
    });
    section.addEventListener("click", event => {
      const button = event.target.closest("[data-up],[data-down]");
      if (!button) return;
      const row = button.closest("[data-row]");
      if (button.hasAttribute("data-up") && row.previousElementSibling) row.previousElementSibling.before(row);
      else if (button.hasAttribute("data-down") && row.nextElementSibling) row.nextElementSibling.after(row);
      reorder(section); button.focus();
    });
    section.addEventListener("dragstart", event => {if (event.target.matches("[data-drag]")) {dragged = event.target.closest("[data-row]"); event.dataTransfer.setData("text/plain", prefix);}});
    section.addEventListener("dragover", event => {if (dragged && dragged.closest("[data-formset]") === section) event.preventDefault();});
    section.addEventListener("drop", event => {
      const target = event.target.closest("[data-row]");
      if (!dragged || !target || dragged === target || dragged.closest("[data-formset]") !== section) return;
      event.preventDefault(); target.before(dragged); reorder(section); dragged.querySelector("[data-drag]").focus(); dragged = null;
    });
    section.addEventListener("dragend", () => {dragged = null;});
  });
  editor.addEventListener("input", event => {if (!event.target.name.endsWith("-dependencies")) update();});
  update();
})();
