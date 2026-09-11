import {Fragment} from "react";

type Span = {text: string; bold?: boolean; italic?: boolean};
type Block = {type: "paragraph" | "heading2" | "heading3" | "quote"; content: Span[]} | {type: "bullet_list" | "ordered_list"; items: Span[][]};
type Document = {schema: "kairos-rich-text-v1"; blocks: Block[]};

function validated(value: unknown, text: string): Document | null {
  try {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const doc = value as Document;
    if (Object.keys(doc).sort().join() !== "blocks,schema" || doc.schema !== "kairos-rich-text-v1" || !Array.isArray(doc.blocks) || !doc.blocks.length || doc.blocks.length > 1000) return null;
    let chars = 0, spans = 0, items = 0;
    function inline(values: Span[]) {
      if (!Array.isArray(values) || values.length > 5000) throw Error("invalid spans");
      return values.map(span => {
        if (!span || typeof span !== "object" || typeof span.text !== "string" || Object.keys(span).some(key => !["text", "bold", "italic"].includes(key)) || [span.bold, span.italic].some(mark => mark !== undefined && typeof mark !== "boolean")) throw Error("invalid span");
        chars += span.text.length; spans++;
        if (chars > 100000 || spans > 5000 || span.text.includes("\0")) throw Error("text limit");
        return span.text;
      }).join("");
    }
    const plain = doc.blocks.map(block => {
      if (!block || typeof block !== "object") throw Error("invalid block");
      if (block.type === "bullet_list" || block.type === "ordered_list") {
        if (Object.keys(block).sort().join() !== "items,type" || !Array.isArray(block.items) || !block.items.length) throw Error("invalid list");
        items += block.items.length; if (items > 1000) throw Error("list limit");
        return block.items.map(inline).join("\n");
      }
      if (!["paragraph", "heading2", "heading3", "quote"].includes(block.type) || Object.keys(block).sort().join() !== "content,type" || !("content" in block)) throw Error("invalid block");
      return inline(block.content);
    }).join("\n\n").trim();
    return plain === text.trim() ? doc : null;
  } catch {return null;}
}

function inline(spans: Span[]) {
  return spans.map((span, index) => {
    let text = <Fragment>{span.text}</Fragment>;
    if (span.bold) text = <strong>{text}</strong>;
    if (span.italic) text = <em>{text}</em>;
    return <Fragment key={index}>{text}</Fragment>;
  });
}

export function RichText({value, text}: {value: unknown; text: string}) {
  const document = validated(value, text);
  if (!document) return <p className="preserve-text">{text}</p>;
  return <div className="rich-text">{document.blocks.map((block, index) => {
    if (block.type === "bullet_list" || block.type === "ordered_list") {
      const children = block.items.map((item, key) => <li key={key}>{inline(item)}</li>);
      return block.type === "bullet_list" ? <ul key={index}>{children}</ul> : <ol key={index}>{children}</ol>;
    }
    if (!("content" in block)) return null;
    const children = inline(block.content);
    if (block.type === "heading2") return <h3 key={index}>{children}</h3>;
    if (block.type === "heading3") return <h4 key={index}>{children}</h4>;
    if (block.type === "quote") return <blockquote key={index}>{children}</blockquote>;
    return <p key={index}>{children}</p>;
  })}</div>;
}
